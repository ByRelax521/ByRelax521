"""BLOOM — süreli ekran oturumu: ekranı görme ve (ayrıca izinle) fareyle/klavyeyle denetleme. Örn. tarayıcıda bir siteyi kullanmak, Spotify’da şarkı açmak.

İZİN KULLANICIDADIR: model yalnızca `iste` diyebilir; HUD'da bir onay kartı çıkar, kullanıcı BAK / KONTROL / REDDET'e kendisi basar
(model kendi kendine izin veremez). Oturum süreli (1-60 dk), ekranda görünür gösterge ve DURDUR düğmesi vardır; süre dolunca kapanır.

  bak       bütün ekranın görüntüsünü alır (koordinatlar 0-1000 normalleştirilmiş: x soldan sağa, y yukarıdan aşağı)
  tikla / surukle / kaydir / yaz / tus   yalnızca KONTROL izninde
  pencereler / ac(uygulama)   açık pencereleri listeler (görev çubuğu gibi) / birini öne alır (küçültülmüşse geri getirir)
  pencere=jarvis   (bak/tikla/surukle/kaydir/yaz/tus) BLOOM'un KENDİ penceresi: koordinatlar pencereye göredir; kontrol için pencere öne alınır.
                   İzin kartı bekliyorsa kendi pencerede işlem yapılmaz; BLOOM girdi gönderdikten ~3 sn içinde kart onayı da reddedilir.
Güvenlik: ESC tuşu basılıysa oturum anında biter; hedef noktada BLOOM penceresi varsa tıklanmaz; başlığında şifre/banka/ödeme/giriş gibi sözler
olan pencerelere yazılmaz ve tıklanmaz; win/alt+f4 gibi tuş birleşimleri engelli; en çok 300 eylem, eylemler arası ≥0,35 sn.
Windows'ta ctypes (user32). Başka platformda yalnızca kendi API'nizi (test) takabilirsiniz.
"""

from __future__ import annotations
import os
import threading
import time
from .log import log

MIN_DK, MAX_DK, VARSAYILAN_DK = 1, 60, 10
ISTEK_OMRU = 90.0
MAX_ISLEM = 300
MIN_ARALIK = 0.35
YAZI_MAX = 300
GORUNTU_KENAR = 1280
ENGEL_SOZ = ('şifre', 'sifre', 'password', 'parola', 'passcode', 'banka', 'bank', 'ödeme', 'odeme', 'payment', 'paypal', 'cüzdan', 'cuzdan', 'wallet',
             'kredi kart', 'credit card', 'iban', 'giriş yap', 'giris yap', 'oturum aç', 'oturum ac', 'sign in', 'log in', 'login',
             '1password', 'bitwarden', 'keepass', 'lastpass', 'kimlik doğrulama', 'two-factor', '2fa', 'e-devlet')
YASAK_TUS = ('win', 'windows', 'cmd', 'meta', 'alt+f4', 'ctrl+alt+delete', 'ctrl+shift+delete', 'ctrl+shift+esc')
VK = {'enter': 0x0D, 'return': 0x0D, 'esc': 0x1B, 'escape': 0x1B, 'tab': 0x09, 'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E, 'space': 0x20,
      'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
      'ctrl': 0x11, 'control': 0x11, 'shift': 0x10, 'alt': 0x12}
VK.update({f'f{i}': 0x6F + i for i in range(1, 13)})
SENTETIK_BEKLE = 3.0      # sentetik girdiden sonra bu kadar sn içinde gelen 'izin' tıklaması reddedilir (kendi kendine onay engeli)
_L = threading.RLock()
OT: dict = {'acik': False, 'kontrol': False, 'bitis': 0.0, 'baslangic': 0.0, 'istek': None, 'islem': 0, 'son_islem': 0.0, 'zamanlayici': None, 'sentetik': 0.0}


def _ek():
    from . import ek
    return ek


def _hud() -> None:
    try:
        _ek()._hud_durum()
    except Exception:
        pass


# --------------------------------------------------------------------------- Windows API (sahte ile değiştirilebilir)
class WinAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c, self.w = ctypes, wintypes
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.u.WindowFromPoint.argtypes = [wintypes.POINT]
        self.u.WindowFromPoint.restype = wintypes.HWND
        self.u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.u.GetAncestor.restype = wintypes.HWND
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.u.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        self.u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
        for ad in ('IsWindowVisible', 'IsIconic', 'SetForegroundWindow', 'BringWindowToTop'):
            f = getattr(self.u, ad)
            f.argtypes = [wintypes.HWND]
            f.restype = wintypes.BOOL
        self.u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetWindowLongPtrW.restype = ctypes.c_ssize_t

    def _dpi(self):
        return self.u.SetThreadDpiAwarenessContext(self.c.c_void_p(-4))

    def _geri(self, eski):
        self.u.SetThreadDpiAwarenessContext(eski)

    def ekran(self):
        eski = self._dpi()
        try:
            return self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77), self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
        finally:
            self._geri(eski)

    def yakala(self):
        from . import ek_paket
        return ek_paket._tum_ekran()

    def _baslik(self, hwnd):
        if not hwnd:
            return '', 0
        n = self.u.GetWindowTextLengthW(hwnd)
        buf = self.c.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        pid = self.w.DWORD(0)
        self.u.GetWindowThreadProcessId(hwnd, self.c.byref(pid))
        return buf.value, int(pid.value)

    def on_pencere(self):
        b, pid = self._baslik(self.u.GetForegroundWindow())
        return b, pid == os.getpid()

    def pencere_noktada(self, x: int, y: int):
        eski = self._dpi()
        try:
            h = self.u.WindowFromPoint(self.w.POINT(int(x), int(y)))
            kok = self.u.GetAncestor(h, 2) or h
            b, pid = self._baslik(kok)
            return b, pid == os.getpid()
        finally:
            self._geri(eski)

    def imle(self, x: int, y: int):
        eski = self._dpi()
        try:
            self.u.SetCursorPos(int(x), int(y))
        finally:
            self._geri(eski)

    def fare(self, dugme: str, asagi: bool):
        bayrak = {'sol': (0x0002, 0x0004), 'sag': (0x0008, 0x0010)}[dugme]
        self.u.mouse_event(bayrak[0] if asagi else bayrak[1], 0, 0, 0, 0)

    def tekerlek(self, adim: int):
        self.u.mouse_event(0x0800, 0, 0, self.w.DWORD(int(adim * 120) & 0xFFFFFFFF), 0)

    def tus(self, vk: int, asagi: bool):
        self.u.keybd_event(vk, 0, 0 if asagi else 2, 0)

    def karakter(self, ch: str):
        c, w = self.c, self.w

        class KI(c.Structure):
            _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]

        class MI(c.Structure):
            _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD), ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]

        class GIRDI(c.Structure):
            class _U(c.Union):
                _fields_ = [('ki', KI), ('mi', MI)]
            _anonymous_ = ('u',)
            _fields_ = [('type', w.DWORD), ('u', _U)]
        for yukari in (0, 2):
            g = GIRDI(type=1)
            g.ki = KI(0, ord(ch), 0x0004 | yukari, 0, 0)
            self.u.SendInput(1, c.byref(g), c.sizeof(GIRDI))

    def _rect(self, hwnd):
        r = self.w.RECT()
        eski = self._dpi()
        try:
            self.u.GetWindowRect(hwnd, self.c.byref(r))
        finally:
            self._geri(eski)
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def kendi(self):
        """BLOOM sürecinin en uygun üst düzey penceresi: {'hwnd', 'rect': (x,y,w,h), 'baslik', 'simge': bool} ya da None."""
        c, w = self.c, self.w
        adaylar = []
        PROC = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        ben = os.getpid()

        def cb(hwnd, _lp):
            try:
                pid = w.DWORD(0)
                self.u.GetWindowThreadProcessId(hwnd, c.byref(pid))
                if pid.value != ben or not self.u.IsWindowVisible(hwnd):
                    return True
                baslik, _ = self._baslik(hwnd)
                x, y, gw, gh = self._rect(hwnd)
                simge = bool(self.u.IsIconic(hwnd))
                if simge or (gw >= 200 and gh >= 150):
                    adaylar.append((hwnd, (x, y, gw, gh), baslik, simge))
            except Exception:
                pass
            return True
        self.u.EnumWindows.argtypes = [PROC, w.LPARAM]
        self.u.EnumWindows(PROC(cb), 0)
        if not adaylar:
            return None
        on = self.u.GetForegroundWindow()
        for ad in adaylar:
            if ad[0] == on:
                sec = ad
                break
        else:
            sec = max(adaylar, key=lambda z: z[1][2] * z[1][3])
        return {'hwnd': sec[0], 'rect': sec[1], 'baslik': sec[2], 'simge': sec[3]}

    def pencereler(self):
        """Görev çubuğundakine benzer liste: görünür, başlıklı üst düzey pencereler (küçültülmüşler dahil)."""
        c, w = self.c, self.w
        out = []
        PROC = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        on = self.u.GetForegroundWindow()
        try:
            import psutil
        except Exception:
            psutil = None

        def cb(hwnd, _lp):
            try:
                if not self.u.IsWindowVisible(hwnd):
                    return True
                baslik, pid = self._baslik(hwnd)
                if not baslik.strip():
                    return True
                ex = self.u.GetWindowLongPtrW(hwnd, -20)
                if ex & 0x80 and not ex & 0x40000:           # WS_EX_TOOLWINDOW (ve APPWINDOW değil)
                    return True
                if self.u.GetAncestor(hwnd, 4):                # sahipli (iletişim kutusu) → atla
                    return True
                exe = ''
                if psutil is not None:
                    try:
                        exe = psutil.Process(pid).name()
                    except Exception:
                        exe = ''
                out.append({'hwnd': int(hwnd or 0), 'baslik': baslik, 'exe': exe, 'simge': bool(self.u.IsIconic(hwnd)), 'on': hwnd == on,
                            'bizim': pid == os.getpid()})
            except Exception:
                pass
            return True
        self.u.EnumWindows.argtypes = [PROC, w.LPARAM]
        self.u.EnumWindows(PROC(cb), 0)
        return out

    def one_getir(self, hwnd: int) -> bool:
        """Pencereyi (küçültülmüşse geri getirip) öne alır; Windows'un ön plan kilidini Alt tuşuyla aşar."""
        if self.u.IsIconic(hwnd):
            self.u.ShowWindow(hwnd, 9)
            time.sleep(0.3)
        self.u.keybd_event(0x12, 0, 0, 0)
        self.u.keybd_event(0x12, 0, 2, 0)
        self.u.BringWindowToTop(hwnd)
        self.u.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return self.u.GetForegroundWindow() == hwnd

    def kendi_one(self):
        """BLOOM penceresini (küçültülmüşse geri getirip) öne alır."""
        k = self.kendi()
        if not k:
            return None
        if k['simge']:
            self.u.ShowWindow(k['hwnd'], 9)      # SW_RESTORE
            time.sleep(0.35)
        self.u.SetForegroundWindow(k['hwnd'])
        time.sleep(0.3)
        return self.kendi()

    def kendi_yakala(self):
        """BLOOM penceresinin görüntüsü (PIL): önce PrintWindow (örtülü olsa da), boş çıkarsa öne alıp ekrandan kırpar."""
        from PIL import Image, ImageStat
        k = self.kendi()
        if not k:
            return None, None
        if not k['simge']:
            try:
                img = self._printwindow(k)
                if img is not None and max(ImageStat.Stat(img.convert('L')).extrema[0][1] - ImageStat.Stat(img.convert('L')).extrema[0][0], 0) > 8:
                    return img, k
            except Exception:
                pass
        k = self.kendi_one()
        if not k:
            return None, None
        from . import ek_paket
        tum = ek_paket._tum_ekran()
        sx, sy, _, _ = self.ekran()
        x, y, gw, gh = k['rect']
        kutu = (max(0, x - sx), max(0, y - sy), min(tum.size[0], x - sx + gw), min(tum.size[1], y - sy + gh))
        if kutu[2] - kutu[0] < 20 or kutu[3] - kutu[1] < 20:
            return None, k
        return tum.crop(kutu), k

    def _printwindow(self, k):
        from PIL import Image
        c, w = self.c, self.w
        g = c.WinDLL('gdi32', use_last_error=True)
        g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
        g.CreateCompatibleBitmap.argtypes = [w.HDC, c.c_int, c.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
        g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
        g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT]
        g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteDC.argtypes = [w.HDC]
        self.u.GetDC.argtypes = [w.HWND]; self.u.GetDC.restype = w.HDC
        self.u.ReleaseDC.argtypes = [w.HWND, w.HDC]
        self.u.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
        _, _, gw, gh = k['rect']
        if gw <= 0 or gh <= 0:
            return None
        ekran = self.u.GetDC(None)
        mem = g.CreateCompatibleDC(ekran)
        bmp = g.CreateCompatibleBitmap(ekran, gw, gh)
        try:
            onceki = g.SelectObject(mem, bmp)
            ok = self.u.PrintWindow(k['hwnd'], mem, 2)        # PW_RENDERFULLCONTENT
            g.SelectObject(mem, onceki)
            if not ok:
                return None

            class BMI(c.Structure):
                _fields_ = [('biSize', w.DWORD), ('biWidth', w.LONG), ('biHeight', w.LONG), ('biPlanes', w.WORD), ('biBitCount', w.WORD),
                            ('biCompression', w.DWORD), ('biSizeImage', w.DWORD), ('biXPelsPerMeter', w.LONG), ('biYPelsPerMeter', w.LONG),
                            ('biClrUsed', w.DWORD), ('biClrImportant', w.DWORD), ('bmiColors', w.DWORD * 3)]
            bi = BMI(biSize=40, biWidth=gw, biHeight=-gh, biPlanes=1, biBitCount=32)
            buf = c.create_string_buffer(gw * gh * 4)
            if g.GetDIBits(mem, bmp, 0, gh, buf, c.byref(bi), 0) != gh:
                return None
            return Image.frombuffer('RGB', (gw, gh), buf.raw, 'raw', 'BGRX', 0, 1).copy()
        finally:
            g.DeleteObject(bmp); g.DeleteDC(mem); self.u.ReleaseDC(None, ekran)

    def esc_basili(self) -> bool:
        return bool(self.u.GetAsyncKeyState(0x1B) & 0x8000)


API = None


def _api():
    global API
    if API is None:
        from . import paths
        if not getattr(paths, 'IS_WIN', False):
            raise RuntimeError('Ekran oturumu yalnızca Windows’ta çalışır.')
        API = WinAPI()
    return API


# --------------------------------------------------------------------------- kullanıcı düğmesiyle site açma
TARAYICILAR = ('chrome', 'msedge', 'firefox', 'brave', 'opera', 'vivaldi', 'iexplore', 'arc')
SITE_IPUCLARI = {'https://studytracker.com.tr': 'studytracker'}


def site_pencere_sec(pencereler: list[dict], ipucu: str) -> dict | None:
    """Başlığında ipucu geçen TARAYICI penceresi (küçültülmüş olsa da). BLOOM'un kendi penceresi sayılmaz.
    Not: tarayıcı penceresinin başlığı yalnızca ETKİN sekmenin başlığıdır; arkadaki sekmeler bu yolla görünmez."""
    ip = ipucu.casefold()
    for z in pencereler:
        if z.get('bizim'):
            continue
        exe = str(z.get('exe') or '').casefold().replace('.exe', '')
        if exe in TARAYICILAR and ip in str(z.get('baslik') or '').casefold():
            return z
    return None


def site_ac(url: str) -> str:
    """Kullanıcı Fikir Alanım düğmesine bastı (model eylemi DEĞİL; ekran oturumu izni gerekmez). Döner: 'oneal' | 'yeni' (+ yeni sekme)."""
    import webbrowser
    ipucu = SITE_IPUCLARI.get(url, '')
    if ipucu:
        try:
            z = site_pencere_sec(_api().pencereler(), ipucu)
            if z is not None and _api().one_getir(z['hwnd']):
                log('ek: site penceresi öne alındı', ipucu)
                return 'oneal'
        except Exception as exc:
            log('ek: site penceresi aranamadı', type(exc).__name__)
    webbrowser.open_new_tab(url)
    return 'yeni'


# --------------------------------------------------------------------------- oturum
def _kalan() -> float:
    return max(0.0, OT['bitis'] - time.time()) if OT['acik'] else 0.0


def _bitir(neden: str = 'kapatıldı') -> None:
    with _L:
        var = OT['acik']
        z = OT.get('zamanlayici')
        OT.update(acik=False, kontrol=False, bitis=0.0, islem=0, zamanlayici=None)
        OT['istek'] = None
    if z is not None:
        try:
            z.cancel()
        except Exception:
            pass
    if var:
        log('ek_ekran: oturum bitti', neden)
        try:
            from . import ek_isler
            ek_isler.teslim_et('ekran:bitti', f'[EKRAN OTURUMU BİTTİ: {neden}] Ekrana erişimin kapandı; yeniden gerekirse ekran(eylem=iste) de.')
        except Exception:
            pass
    _hud()


def _zaman_asimi() -> None:
    if OT['acik'] and time.time() >= OT['bitis'] - 0.2:
        _bitir('süre doldu')


def _ac(kontrol: bool, dakika: float) -> None:
    dakika = max(MIN_DK, min(MAX_DK, float(dakika or VARSAYILAN_DK)))
    with _L:
        eski = OT.get('zamanlayici')
        if eski is not None:
            try:
                eski.cancel()
            except Exception:
                pass
        OT.update(acik=True, kontrol=bool(kontrol), baslangic=time.time(), bitis=time.time() + dakika * 60, islem=0, son_islem=0.0, istek=None)
        t = threading.Timer(dakika * 60 + 0.5, _zaman_asimi)
        t.daemon = True
        OT['zamanlayici'] = t
        t.start()
    log('ek_ekran: oturum açıldı', 'kontrol' if kontrol else 'bak', f'{dakika:.0f} dk')
    _hud()


def hud_durum() -> dict:
    """HUD için: onay kartı ve etkin oturum göstergesi."""
    with _L:
        i = OT.get('istek')
        if i and time.time() - i['t'] > ISTEK_OMRU:
            OT['istek'] = None
            i = None
        return {'acik': bool(OT['acik'] and _kalan() > 0), 'kontrol': bool(OT['kontrol']), 'bitis': OT['bitis'],
                'istek': ({'kontrol': i['kontrol'], 'dakika': i['dakika'], 'neden': i['neden'], 'bitis': i['t'] + ISTEK_OMRU} if i else None)}


def hud_olay(data: dict):
    """HUD düğmeleri: izin (kontrol=bool, dakika) | reddet | durdur."""
    e = str((data or {}).get('eylem') or '')
    if e == 'izin':
        with _L:
            i = OT.get('istek')
            if not i or time.time() - i['t'] > ISTEK_OMRU:
                OT['istek'] = None
                _hud()
                return 'istek yok ya da süresi doldu'
            if time.time() - OT.get('sentetik', 0.0) < SENTETIK_BEKLE:
                log('ek_ekran: izin tıklaması reddedildi (az önce BLOOM girdi gönderdi)')
                return 'izin verilmedi: az önce BLOOM fare/klavye kullandı; kartı kendin, birkaç saniye sonra tekrar onayla'
            kontrol = bool((data or {}).get('kontrol'))
            dk = (data or {}).get('dakika') or i['dakika']
        _ac(kontrol, dk)
        try:
            from . import ek_isler
            ek_isler.teslim_et('ekran:izin', f'[EKRAN İZNİ VERİLDİ: {"KONTROL (tıklama/klavye)" if kontrol else "yalnızca BAKMA"}, '
                                             f'{max(MIN_DK, min(MAX_DK, int(float(dk))))} dk] Şimdi ekran(eylem=bak) ile bakabilirsin.')
        except Exception:
            pass
        return True
    if e == 'reddet':
        with _L:
            OT['istek'] = None
        _hud()
        try:
            from . import ek_isler
            ek_isler.teslim_et('ekran:red', '[EKRAN İZNİ REDDEDİLDİ] Kullanıcı ekran erişimini vermedi; ısrar etme.')
        except Exception:
            pass
        return True
    if e == 'durdur':
        _bitir('kullanıcı durdurdu')
        return True
    return False


# --------------------------------------------------------------------------- yardımcılar
def _yok() -> str:
    return 'Ekran oturumu kapalı. Kullanıcı istediyse ekran(eylem=iste) de; izni kullanıcı ekrandaki karttan verir.'


def _kontrol_gerekli() -> str:
    if not OT['acik'] or _kalan() <= 0:
        return _yok()
    if not OT['kontrol']:
        return 'Bu oturum yalnızca BAKMA izni veriyor; tıklama/yazma için kullanıcının KONTROL izni vermesi gerekir (ekran(eylem=iste, kontrol=true)).'
    return ''


def _katla(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize('NFKD', (s or '').replace('ı', 'i').replace('İ', 'i'))
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold().strip()


def degisim_orani(a, b, kucult=4, esik=28) -> float:
    """İki ekran görüntüsü arasında değişen piksel oranı (0-1)."""
    import numpy as np
    from PIL import Image
    if a is None or b is None or a.size != b.size:
        return 1.0
    w, h = a.size
    ga = np.asarray(a.convert('L').resize((max(1, w // kucult), max(1, h // kucult)), Image.BOX), dtype=np.int16)
    gb = np.asarray(b.convert('L').resize((max(1, w // kucult), max(1, h // kucult)), Image.BOX), dtype=np.int16)
    return float((np.abs(ga - gb) > esik).mean())


def _once(api):
    try:
        return api.yakala()
    except Exception:
        return None


def _degisim_notu(api, once, bekle=0.3) -> str:
    """Eylemden sonra ekran gerçekten değişti mi — PİKSEL KANITI (modelin 'oldu sanmasını' engeller)."""
    if once is None:
        return ''
    try:
        time.sleep(bekle)
        sonra = api.yakala()
        o = degisim_orani(once, sonra)
    except Exception:
        return ''
    if o < 0.0004:
        return ' ⚠ EKRANDA HİÇBİR DEĞİŞİKLİK görülmedi: eylem etkisiz kalmış olabilir (hedef doğru mu, pencere önde mi?). Başarılı SAYMA; bak ile kontrol et.'
    return f' (Ekran değişti: %{o * 100:.1f}.)'


def _sentetik() -> None:
    OT['sentetik'] = time.time()


def _kendi_mi(a: dict) -> bool:
    return str((a or {}).get('pencere') or '').lower() in ('jarvis', 'kendi', 'kendi_pencere', 'jarvis_penceresi')


def _kendi_hazir(api, kontrol: bool):
    """BLOOM'un kendi penceresi üzerinde işlem: (alan=(x,y,w,h), hata). Kontrol için pencereyi öne alır."""
    if kontrol:
        if hud_durum()['istek']:
            return None, 'Kullanıcının izin kartı ekranda bekliyor; o kart kullanıcıya aittir, BLOOM kendi penceresinde işlem yapmaz. Kartı kullanıcı yanıtlasın.'
        k = api.kendi_one()
    else:
        k = api.kendi()
    if not k:
        return None, 'BLOOM penceresi bulunamadı (kapalı ya da tepsiye gizlenmiş olabilir).'
    return k['rect'], ''


def _guvenlik_ve_hiz(api) -> str:
    """Eylemden önce: ESC, süre, sayaç, hız."""
    try:
        if api.esc_basili():
            _bitir('ESC ile acil durdurma')
            return 'ESC basılı olduğu için ekran oturumu KAPATILDI (acil durdurma).'
    except Exception:
        pass
    bekle, sinir = 0.0, False
    with _L:
        if _kalan() <= 0:
            return _yok()
        if OT['islem'] >= MAX_ISLEM:
            sinir = True
        else:
            OT['islem'] += 1
            bekle = MIN_ARALIK - (time.time() - OT['son_islem'])
            OT['son_islem'] = time.time() + max(0.0, bekle)
    if sinir:
        _bitir('eylem sınırına ulaşıldı')
        return f'Bu oturumda en çok {MAX_ISLEM} eylem yapılabilir; oturum kapandı.'
    if bekle > 0:
        time.sleep(bekle)
    _sentetik()
    return ''


def _piksel(api, nx, ny, alan=None):
    x0, y0, w, h = alan or api.ekran()
    nx = max(0.0, min(1000.0, float(nx)))
    ny = max(0.0, min(1000.0, float(ny)))
    return int(x0 + nx / 1000.0 * (w - 1)), int(y0 + ny / 1000.0 * (h - 1))


def _engelli_mi(baslik: str) -> str:
    b = (baslik or '').lower()
    for k in ENGEL_SOZ:
        if k in b:
            return k
    return ''


def _hedef_kontrol(api, px: int, py: int, kendi: bool = False) -> str:
    try:
        baslik, bizim = api.pencere_noktada(px, py)
    except Exception:
        return ''
    if kendi:
        if not bizim:
            return f'Hedef noktada BLOOM penceresi görünmüyor (üstünde “{(baslik or "başka bir pencere")[:40]}” var); tıklanmadı. bak(pencere=jarvis) ile yeniden bak.'
        return ''
    if bizim:
        return 'Hedef noktada BLOOM’un kendi penceresi var; tıklanmadı. BLOOM’un kendi arayüzünü kullanmak istiyorsan pencere=jarvis ver; tarayıcıdaki bir hedefse kullanıcıdan tarayıcıyı öne almasını (ya da BLOOM’u küçültmesini) iste.'
    k = _engelli_mi(baslik)
    if k:
        return f'Hedef pencerenin başlığında “{k}” geçiyor ("{baslik[:50]}"); güvenlik gereği tıklanmadı/yazılmadı.'
    return ''


def _jpeg_ekle(img, ctx) -> tuple[int, int]:
    import io
    from PIL import Image
    g = img.convert('RGB')
    w, h = g.size
    k = min(1.0, GORUNTU_KENAR / max(w, h))
    if k < 1.0:
        g = g.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    g.save(buf, 'JPEG', quality=82)
    if ctx is not None and hasattr(ctx, 'images'):
        ctx.images.append(buf.getvalue())
    return g.size


def _isaret(img, noktalar):
    """Görüntüye (PIL.ImageDraw kullanmadan) renkli kareler koyar: noktalar = [(px, py, (r,g,b)), ...]"""
    from PIL import Image
    g = img.convert('RGB')
    w, h = g.size
    r = max(4, min(w, h) // 120)
    for px, py, renk in noktalar:
        kutu = Image.new('RGB', (2 * r + 1, 2 * r + 1), renk)
        g.paste(kutu, (max(0, min(w - 1, int(px) - r)), max(0, min(h - 1, int(py) - r))))
    return g


def _xy(a: dict, ad: str):
    v = a.get(ad)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return float(v[0]), float(v[1])
    return None


def _nokta(a: dict, xk='x', yk='y'):
    try:
        return float(a[xk]), float(a[yk])
    except (KeyError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- araç
def _tikla_px(api, px, py, dugme='sol', cift=False):
    api.imle(px, py)
    time.sleep(0.06)
    for _ in range(2 if cift else 1):
        api.fare(dugme, True)
        time.sleep(0.04)
        api.fare(dugme, False)
        time.sleep(0.06)
    _sentetik()


def _surukle_px(api, p1, p2):
    api.imle(*p1)
    time.sleep(0.08)
    api.fare('sol', True)
    time.sleep(0.08)
    adim = 12
    for i in range(1, adim + 1):
        api.imle(int(p1[0] + (p2[0] - p1[0]) * i / adim), int(p1[1] + (p2[1] - p1[1]) * i / adim))
        time.sleep(0.02)
    time.sleep(0.08)
    api.fare('sol', False)
    _sentetik()


def arac(a: dict, _c=None) -> str:
    a = a or {}
    eylem = str(a.get('eylem') or 'durum').lower()
    try:
        if eylem == 'iste':
            kontrol = bool(a.get('kontrol'))
            try:
                dk = max(MIN_DK, min(MAX_DK, float(a.get('dakika') or VARSAYILAN_DK)))
            except (TypeError, ValueError):
                dk = VARSAYILAN_DK
            _api()
            with _L:
                OT['istek'] = {'t': time.time(), 'kontrol': kontrol, 'dakika': dk, 'neden': ' '.join(str(a.get('neden') or '').split())[:140]}
            _hud()
            return (f'İzin kartı ekranda gösterildi ({"KONTROL" if kontrol else "BAKMA"}, {dk:.0f} dk). KARARI KULLANICI VERİR: onayı ekrandaki düğmeden verecek; '
                    f'{int(ISTEK_OMRU)} sn içinde basmazsa kart kapanır. Kullanıcıya kartı söyle ve bekle; onaylanınca sana bildirim gelir. Kendi kendine izin verilmiş sayma.')
        if eylem == 'durum':
            if not OT['acik'] or _kalan() <= 0:
                return 'Ekran oturumu kapalı.' + (' (İzin isteği kullanıcıda bekliyor.)' if hud_durum()['istek'] else '')
            return f'Ekran oturumu AÇIK ({"KONTROL" if OT["kontrol"] else "yalnızca bakma"}); kalan {int(_kalan() // 60)} dk {int(_kalan() % 60)} sn; {OT["islem"]}/{MAX_ISLEM} eylem.'
        if eylem == 'kapat':
            if not OT['acik']:
                return 'Ekran oturumu zaten kapalı.'
            _bitir('BLOOM kapattı')
            return 'Ekran oturumu kapatıldı.'
        if not OT['acik'] or _kalan() <= 0:
            if OT['acik']:
                _bitir('süre doldu')
            return _yok()
        api = _api()
        if eylem == 'pencereler':
            lst = api.pencereler()
            if not lst:
                return 'Açık pencere bulunamadı.'
            satir = [f'{i + 1}. {z["exe"] or "?"} — “{z["baslik"][:70]}”{" [öndeki]" if z["on"] else ""}{" [küçültülmüş]" if z["simge"] else ""}{" [BLOOM]" if z.get("bizim") else ""}'
                     for i, z in enumerate(lst[:40])]
            return ('Açık pencereler (görev çubuğu gibi; ekran görüntüsü gerekmeden):\n' + '\n'.join(satir) +
                    '\nBirini öne almak için ekran(eylem=ac, uygulama=\"ad\") (KONTROL izni gerekir).')
        if eylem == 'bak':
            try:
                if api.esc_basili():
                    _bitir('ESC ile acil durdurma')
                    return 'ESC basılı olduğu için ekran oturumu KAPATILDI.'
            except Exception:
                pass
            if _kendi_mi(a):
                img, k = api.kendi_yakala()
                if img is None:
                    return 'BLOOM penceresinin görüntüsü alınamadı (pencere bulunamadı ya da küçültülmüş/boş).'
                boyut = _jpeg_ekle(img, _c)
                return (f'BLOOM’un KENDİ penceresinin görüntüsü eklendi ({boyut[0]}x{boyut[1]}; “{(k or {}).get("baslik", "")[:60]}”). Koordinatlar 0-1000 ve bu PENCEREYE göre. '
                        f'Bunu tıklamak için tikla/yaz/tus komutlarına pencere=jarvis ver (KONTROL izni gerekir). Kalan: {int(_kalan() // 60)} dk. Gördüğünü uydurma.')
            img = api.yakala()
            boyut = _jpeg_ekle(img, _c)
            baslik, bizim = api.on_pencere()
            ek = ' BLOOM penceresi önde: tarayıcı/hedef pencere arkada kalmış olabilir; gerekirse kullanıcıdan öne almasını iste. (BLOOM’un kendisine bakmak için pencere=jarvis ver.)' if bizim else ''
            tahta = ''
            return (f'Ekran görüntüsü eklendi ({boyut[0]}x{boyut[1]}). Koordinatlar 0-1000 (x soldan sağa, y yukarıdan aşağı). Öndeki pencere: “{baslik[:80]}”.{ek}{tahta} '
                    f'Kalan: {int(_kalan() // 60)} dk. Gördüğünü uydurma: net değilse tekrar bak ya da kullanıcıya sor.')
        # --- kontrol eylemleri
        kont = _kontrol_gerekli()
        if kont:
            return kont
        if eylem == 'ac':
            ad = _katla(str(a.get('uygulama') or ''))
            if not ad:
                return 'uygulama gerekli (ör. Spotify, Chrome). Önce ekran(eylem=pencereler) ile listeye bak.'
            lst = [z for z in api.pencereler()]
            tam = [z for z in lst if _katla(z['exe']).replace('.exe', '') == ad or _katla(z['baslik']).startswith(ad)]
            icerir = [z for z in lst if ad in _katla(z['exe']) or ad in _katla(z['baslik'])]
            aday = (tam or icerir)
            if not aday:
                return f'“{a.get("uygulama")}” adlı açık pencere yok. Uygulama kapalıysa open_app aracıyla açılır; açıklar: ' + ', '.join(sorted({z['exe'] or z['baslik'][:20] for z in lst})[:12])
            h = _guvenlik_ve_hiz(api)
            if h:
                return h
            z = aday[0]
            once = _once(api)
            ok = api.one_getir(z['hwnd'])
            _sentetik()
            return (f'“{z["exe"] or z["baslik"][:30]}” penceresi öne alındı.' if ok else f'“{z["exe"] or z["baslik"][:30]}” öne alınamadı (Windows engellemiş olabilir); ekran(bak) ile ne olduğuna bak.') + _degisim_notu(api, once, 0.2) + ' Şimdi bak ile doğrula.'
        if eylem in ('tikla', 'surukle', 'kaydir'):
            n1 = _nokta(a, 'x', 'y')
            if n1 is None:
                return 'x ve y gerekli (0-1000).'
            kendi = _kendi_mi(a)
            alan = None
            if kendi:
                alan, h = _kendi_hazir(api, True)
                if h:
                    return h
            p1 = _piksel(api, *n1, alan)
            if eylem == 'surukle':
                n2 = _nokta(a, 'x2', 'y2')
                if n2 is None:
                    return 'x2 ve y2 gerekli (0-1000).'
                p2 = _piksel(api, *n2, alan)
            for p in ((p1, p2) if eylem == 'surukle' else (p1,)):
                h = _hedef_kontrol(api, *p, kendi)
                if h:
                    return h
            h = _guvenlik_ve_hiz(api)
            if h:
                return h
            once = _once(api)
            if eylem == 'tikla':
                _tikla_px(api, *p1, 'sag' if str(a.get('dugme') or '').lower() in ('sag', 'sağ', 'right') else 'sol', bool(a.get('cift')))
                return f'Tıklandı ({n1[0]:.0f},{n1[1]:.0f}).' + _degisim_notu(api, once) + ' Sonucu bak ile doğrula.'
            if eylem == 'surukle':
                _surukle_px(api, p1, p2)
                return 'Sürüklendi.' + _degisim_notu(api, once) + ' Sonucu bak ile doğrula.'
            api.imle(*p1)
            try:
                adim = int(float(a.get('miktar') or -3))
            except (TypeError, ValueError):
                adim = -3
            once = _once(api)
            api.tekerlek(max(-20, min(20, adim)))
            return 'Kaydırıldı (negatif = aşağı).' + _degisim_notu(api, once) + ' Sonucu bak ile doğrula.'
        if eylem == 'yaz':
            metin = str(a.get('metin') or '')
            if not metin or len(metin) > YAZI_MAX:
                return f'metin 1-{YAZI_MAX} karakter olmalı.'
            kendi = _kendi_mi(a)
            if kendi:
                _al, h = _kendi_hazir(api, True)
                if h:
                    return h
            try:
                baslik, bizim = api.on_pencere()
            except Exception:
                baslik, bizim = '', False
            if bizim and not kendi:
                return 'Öndeki pencere BLOOM’un kendisi; yazılmadı. BLOOM’un kendi arayüzüne yazmak için pencere=jarvis ver; aksi halde hedef pencereyi öne al.'
            if kendi and not bizim:
                return 'BLOOM penceresi öne alınamadı; yazılmadı.'
            k = '' if kendi else _engelli_mi(baslik)
            if k:
                return f'Öndeki pencerenin başlığında “{k}” geçiyor; güvenlik gereği yazılmadı.'
            h = _guvenlik_ve_hiz(api)
            if h:
                return h
            once = _once(api)
            for ch in metin:
                api.karakter(ch)
                time.sleep(0.01)
            _sentetik()
            return f'{len(metin)} karakter gönderildi.' + _degisim_notu(api, once) + ' Sonucu bak ile doğrula.'
        if eylem == 'tus':
            ham = str(a.get('tus') or '').lower().replace(' ', '')
            if not ham:
                return 'tus gerekli (ör. enter, esc, ctrl+z, left).'
            if any(y == ham or (y in ('win', 'windows', 'cmd', 'meta') and y in ham.split('+')) for y in YASAK_TUS):
                return f'“{ham}” tuş birleşimi güvenlik gereği engelli.'
            parcalar = ham.split('+')
            kodlar = []
            for pc in parcalar:
                if pc in VK:
                    kodlar.append(VK[pc])
                elif len(pc) == 1 and pc.isalnum():
                    kodlar.append(ord(pc.upper()))
                else:
                    return f'Bilinmeyen tuş: {pc}.'
            kendi = _kendi_mi(a)
            if kendi:
                _al, h = _kendi_hazir(api, True)
                if h:
                    return h
            baslik, bizim = api.on_pencere()
            if bizim and not kendi:
                return 'Öndeki pencere BLOOM’un kendisi; tuş gönderilmedi. BLOOM’un kendi arayüzü için pencere=jarvis ver.'
            if kendi and not bizim:
                return 'BLOOM penceresi öne alınamadı; tuş gönderilmedi.'
            k = '' if kendi else _engelli_mi(baslik)
            if k:
                return f'Öndeki pencerenin başlığında “{k}” geçiyor; tuş gönderilmedi.'
            h = _guvenlik_ve_hiz(api)
            if h:
                return h
            once = _once(api)
            for kd in kodlar:
                api.tus(kd, True)
            for kd in reversed(kodlar):
                api.tus(kd, False)
            _sentetik()
            return f'Tuş gönderildi: {ham}.' + _degisim_notu(api, once) + ' Sonucu bak ile doğrula.'
        return 'Bilinmeyen eylem. Geçerli: iste, durum, bak, pencereler, ac, tikla, surukle, kaydir, yaz, tus, kapat.'
    except Exception as exc:
        log('ek_ekran: hata', eylem, type(exc).__name__, exc)
        return f'Ekran hatası: {type(exc).__name__}: {str(exc)[:200]}'


# --------------------------------------------------------------------------- özgün Windows araçlarına küçük düzeltmeler
SPOTIFY_ESKI = 'araması açıldı'
SPOTIFY_YENI = ('Spotify uygulaması “{q}” aramasıyla açıldı ama Spotify’ın komut aracı (spotify_cli) bu kurulumda yok, o yüzden çalma başlamadı. '
                'ÇALMAK İÇİN: ekran(eylem=iste, kontrol=true, neden=\"Spotify’da şarkıyı çalmak\") de, kullanıcı karttan onaylayınca ekran(eylem=ac, uygulama=\"Spotify\") '
                '(küçültülmüşse öne gelir), ekran(bak) ile sonuçlara bak, aranan şarkının satırına ÇİFT TIKLA (ekran(eylem=tikla, cift=true)) ya da en iyi sonucun yeşil çal düğmesine tıkla, '
                'sonra bak ile çaldığını DOĞRULA. Tarayıcıdaki YouTube’a DÜŞME; “Spotify’a erişimim yok” DEME.')
ANALIZ_IPUCU = (' [Not: bu yalnızca ÖNDEKİ pencereyi gösterir; görev çubuğunu, başka uygulamaları ya da BLOOM’un kendisini görmek/kullanmak için '
                'ekran(eylem=iste) ile kullanıcıdan izin iste; sonra ekran(bak / pencereler / ac).]')


def _spotify_kayitli() -> bool:
    """`spotify:` URI protokolü kayıtlı mı (Mağaza paketinde klasör okunamasa da Spotify kurulu sayılır)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'spotify'):
            return True
    except Exception:
        return False


def _spotify_calisiyor() -> bool:
    try:
        import psutil
        return any((p.info.get('name') or '').lower() == 'spotify.exe' for p in psutil.process_iter(['name']))
    except Exception:
        return False


def win_yamalari(wm=None, ws=None, kayit=None, calisiyor=None) -> bool:
    """win_media/win_screen işlevlerini (özgün dosyalara dokunmadan) çalışma anında sarar. Tekrar çağrılırsa bir şey yapmaz."""
    try:
        if wm is None:
            from .actions import win_media as wm
        if ws is None:
            from .actions import win_screen as ws
    except Exception as exc:
        log('ek_ekran: win yamaları atlandı', type(exc).__name__)
        return False
    if not getattr(wm, '_ek_yama', False):
        orj_kurulu, orj_play = wm.spotify_installed, wm.play_spotify

        def kurulu():
            try:
                if orj_kurulu():
                    return True
            except Exception:
                pass
            return bool((kayit or _spotify_kayitli)()) or bool((calisiyor or _spotify_calisiyor)())

        def play(query, autoplay=True):
            t0 = time.time()
            r = orj_play(query, autoplay)
            log(f'ek_sure: play_spotify {time.time() - t0:.1f} sn')
            if isinstance(r, str) and SPOTIFY_ESKI in r and 'ilk sonuca' in r:
                return SPOTIFY_YENI.replace('{q}', str(query)[:60])
            return r
        wm.spotify_installed, wm.play_spotify, wm._ek_yama = kurulu, play, True
    if not getattr(ws, '_ek_yama', False):
        orj_analiz = ws.analyze_screen

        def analiz(query, target='active_window'):
            t0 = time.time()
            if (target or 'active_window').strip().lower() != 'active_window':
                return 'Ekran analizi yalnızca öndeki pencereyi destekler.' + ANALIZ_IPUCU, []
            metin, resimler = orj_analiz(query, target)
            log(f'ek_sure: analyze_screen {time.time() - t0:.1f} sn')
            return (metin + ANALIZ_IPUCU if resimler else metin), resimler
        ws.analyze_screen, ws._ek_yama = analiz, True
    return True
