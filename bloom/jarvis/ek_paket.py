"""EK Yetenek Paketi (R3.1): üç açık kaynak asistan projesinden aktarılan, V4'te eksik olan yetenekler.

Kaynak fikirler (kod kopyalanmadı; Kalliope GPL-3 olduğu için yalnızca fikir alındı):
  - GauravSingh9356/J.A.R.V.I.S : haberler, sözlük (yazım önerisi), Vikipedi, e-posta, ekran görüntüsü
  - kishanrajput23/Bloom-Desktop-Voice-Assistant : kapat/yeniden başlat, ekran görüntüsü, Vikipedi
  - kalliope-project/kalliope   : sinyal → nöron zinciri  ==> makro (kendi komutlarını öğret)

Araçlar: vikipedi, sozluk, haberler, eposta_taslagi, guc_islemi, ekran_goruntusu, makro.
Hepsi yerel ve anahtarsız: Vikipedi REST, TDK (sozluk.gov.tr), Google Haber RSS.
Windows'a özgü olanlar (güç, ekran görüntüsü) Linux'ta denenemedi; hata yolları güvenli.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import threading
import unicodedata
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path

from .log import log

IS_WIN = sys.platform.startswith('win')
UA = {'User-Agent': 'BLOOM-EK/3.1 (+yerel asistan)'}
_L = threading.RLock()
_S = {'reg': None, 'makrolar': None, 'calisiyor': set()}

MAKRO_ENGEL = {'makro', 'guc_islemi', 'shell_run', 'yetenek_yonet', 'delete_memory', 'clear_notes', 'quit_app',
               'offer_disable_others', 'final_choice', 'secret_topic'}
MAKRO_MAX_ADIM = 8


def _ek():
    from . import ek
    return ek


def _kayit_reg(registry) -> None:
    _S['reg'] = registry


def _sade(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s or '').casefold().replace('ı', 'i'))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', s)).strip()


def _get(url: str, params: dict | None = None, timeout: float = 8.0):
    import requests
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


# --------------------------------------------------------------------------- Vikipedi
def vikipedi(konu: str, dil: str = 'tr') -> str:
    konu = (konu or '').strip()
    if not konu:
        return 'Hata: hangi konuyu arayacağımı söylemelisin.'
    dil = dil if dil in ('tr', 'en', 'de', 'fr', 'es', 'it', 'ru', 'ar') else 'tr'
    try:
        ara = _get(f'https://{dil}.wikipedia.org/w/api.php',
                   {'action': 'query', 'list': 'search', 'srsearch': konu, 'srlimit': 1, 'format': 'json',
                    'utf8': 1, 'srprop': ''}).json()
        bulunan = (ara.get('query') or {}).get('search') or []
        if not bulunan:
            return f'Vikipedi\'de “{konu}” için sonuç bulamadım ({dil}).'
        baslik = bulunan[0]['title']
        ozet = _get(f'https://{dil}.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(baslik.replace(' ', '_'), safe='')).json()
    except Exception as exc:
        log('ek_paket: vikipedi hatası', type(exc).__name__, exc)
        return 'Hata: Vikipedi\'ye ulaşamadım (internet ya da servis sorunu).'
    metin = (ozet.get('extract') or '').strip()
    if not metin:
        return f'Vikipedi\'de “{baslik}” sayfası var ama özeti boş.'
    if len(metin) > 1100:
        metin = metin[:1100].rsplit('. ', 1)[0].rstrip() + '.'
    url = ((ozet.get('content_urls') or {}).get('desktop') or {}).get('page', '')
    belirsiz = ' (Dikkat: bu bir anlam ayrımı sayfası; kullanıcıya hangisini kastettiğini sor.)' if ozet.get('type') == 'disambiguation' else ''
    return f'{ozet.get("title", baslik)}: {metin}{belirsiz}\nKaynak: Vikipedi {url}'.strip()


# --------------------------------------------------------------------------- TDK sözlük
def sozluk(kelime: str) -> str:
    kelime = (kelime or '').strip()
    if not kelime:
        return 'Hata: hangi kelimeyi arayacağımı söylemelisin.'
    try:
        veri = _get('https://sozluk.gov.tr/gts', {'ara': kelime}).json()
    except Exception as exc:
        log('ek_paket: sözlük hatası', type(exc).__name__, exc)
        return 'Hata: TDK sözlüğüne ulaşamadım (internet ya da servis sorunu).'
    if isinstance(veri, dict) or not veri:           # {"error": "Sonuç bulunamadı"}
        # TDK'nin herkese açık bir öneri uç noktası kalmadı (/oneri artık HTML dönüyor): düzeltmeyi model yapar.
        return (f'TDK’de “{kelime}” bulunamadı. Yazım hatası olabilir: doğru yazımı tahmin edip sozluk\'ü BİR KEZ daha dene; '
                'yine yoksa kelimenin sözlükte olmadığını söyle.')
    parcalar = []
    for m in veri[:3]:
        madde = html.unescape(re.sub(r'<[^>]+>', '', m.get('madde') or kelime))
        kok = (m.get('lisan') or '').strip()
        satir = [f'{madde}' + (f' ({kok})' if kok else '')]
        for n, a in enumerate((m.get('anlamlarListe') or [])[:5], 1):
            oz = ', '.join(x.get('tam_adi', '') for x in (a.get('ozelliklerListe') or []) if x.get('tam_adi'))
            ornek = ''
            if a.get('orneklerListe'):
                ornek = ' Örnek: “' + str(a['orneklerListe'][0].get('ornek', '')).strip() + '”'
            satir.append(f'  {n}. {("[" + oz + "] ") if oz else ""}{str(a.get("anlam", "")).strip()}{ornek}')
        parcalar.append('\n'.join(satir))
    bl = [x.get('madde_duz') or x.get('madde') for x in (veri[0].get('birlesikler') or []) if isinstance(x, dict)]
    ata = ('\nBirleşik sözler: ' + ', '.join(str(x) for x in bl[:5] if x)) if bl else ''
    return '\n'.join(parcalar) + ata + '\nKaynak: TDK Güncel Türkçe Sözlük'


# --------------------------------------------------------------------------- Haberler
_KATEGORI = {'dunya': 'WORLD', 'turkiye': 'NATION', 'ekonomi': 'BUSINESS', 'is': 'BUSINESS', 'teknoloji': 'TECHNOLOGY',
             'spor': 'SPORTS', 'bilim': 'SCIENCE', 'saglik': 'HEALTH', 'magazin': 'ENTERTAINMENT', 'eglence': 'ENTERTAINMENT'}


def _rss_oku(xml: bytes, n: int) -> list[tuple[str, str, str]]:
    kok = ET.fromstring(xml)
    out = []
    for it in kok.iter('item'):
        baslik = html.unescape((it.findtext('title') or '').strip())
        kaynak = (it.findtext('source') or '').strip()
        if kaynak and baslik.endswith(' - ' + kaynak):
            baslik = baslik[:-len(kaynak) - 3].rstrip()
        elif not kaynak and ' - ' in baslik:
            baslik, kaynak = baslik.rsplit(' - ', 1)
        tarih = ''
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(it.findtext('pubDate') or '')
            fark = dt.datetime.now(dt.timezone.utc) - d.astimezone(dt.timezone.utc)
            s = int(fark.total_seconds() // 60)
            tarih = f'{s} dk önce' if s < 60 else (f'{s // 60} sa önce' if s < 1440 else f'{s // 1440} gün önce')
        except Exception:
            pass
        if baslik:
            out.append((baslik, kaynak, tarih))
        if len(out) >= n:
            break
    return out


def haberler(konu: str = '', kategori: str = '', adet: int = 6) -> str:
    adet = max(1, min(int(adet or 6), 10))
    tr = {'hl': 'tr', 'gl': 'TR', 'ceid': 'TR:tr'}
    konu = (konu or '').strip()
    kat = _KATEGORI.get(_sade(kategori)) if kategori else None
    if konu:
        url, params = 'https://news.google.com/rss/search', {'q': konu, **tr}
    elif kat:
        url, params = f'https://news.google.com/rss/headlines/section/topic/{kat}', tr
    else:
        url, params = 'https://news.google.com/rss', tr
    try:
        liste = _rss_oku(_get(url, params, 10).content, adet)
    except Exception as exc:
        log('ek_paket: haber hatası', type(exc).__name__, exc)
        return 'Hata: haberlere ulaşamadım (internet ya da servis sorunu).'
    if not liste:
        return f'“{konu or kategori or "gündem"}” için haber bulamadım.'
    baslik = konu or (kategori or 'gündem')
    satirlar = [f'{i}. {b}' + (f' ({k}{", " + t if t else ""})' if k else '') for i, (b, k, t) in enumerate(liste, 1)]
    return f'Haberler — {baslik} (Google Haberler):\n' + '\n'.join(satirlar) + '\nKısaca özetle; ayrıntı istenirse arastir ya da ozetle kullan.'


# --------------------------------------------------------------------------- E-posta taslağı
def _gecerli_eposta(a: str) -> bool:
    return bool(re.fullmatch(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]{2,}", a or ''))


def eposta_taslagi(alici: str = '', konu: str = '', metin: str = '', saglayici: str = 'gmail') -> str:
    alici = (alici or '').strip()
    if alici and not all(_gecerli_eposta(x.strip()) for x in re.split(r'[;,]', alici) if x.strip()):
        return f'Hata: “{alici}” geçerli bir e-posta adresine benzemiyor. Adresi harf harf netleştir; tahmin etme.'
    if not (konu or metin):
        return 'Hata: en azından bir konu ya da metin gerekli.'
    if (saglayici or '').lower() == 'varsayilan':
        url = 'mailto:' + urllib.parse.quote(alici) + '?' + urllib.parse.urlencode({'subject': konu, 'body': metin}, quote_via=urllib.parse.quote)
    else:
        url = 'https://mail.google.com/mail/?' + urllib.parse.urlencode({'view': 'cm', 'fs': 1, 'to': alici, 'su': konu, 'body': metin})
    try:
        if url.startswith('mailto:') and IS_WIN:
            os.startfile(url)                                   # type: ignore[attr-defined]
        else:
            webbrowser.open(url)
    except Exception as exc:
        return f'Hata: taslak açılamadı ({type(exc).__name__}).'
    return ('E-posta taslağı açıldı' + (f' (alıcı: {alici})' if alici else ' (alıcı boş)') +
            '. GÖNDERİLMEDİ: göndermek için kullanıcının e-posta penceresinde Gönder\'e basması gerekir; bunu ona söyle.')


# --------------------------------------------------------------------------- Güç işlemleri
_GUC = {'kapat': (['shutdown', '/s', '/t'], 'bilgisayar kapanacak'),
        'yeniden_baslat': (['shutdown', '/r', '/t'], 'bilgisayar yeniden başlayacak'),
        'oturum_kapat': (['shutdown', '/l'], 'oturum kapanacak')}


def _calistir(cmd: list[str]) -> tuple[int, str]:
    flags = 0x08000000 if IS_WIN else 0                       # CREATE_NO_WINDOW
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=flags)
    return p.returncode, (p.stdout + p.stderr).strip()


def guc_islemi(islem: str, saniye: int | None = None, onay: bool = False) -> str:
    islem = (islem or '').strip()
    if islem not in ('kapat', 'yeniden_baslat', 'oturum_kapat', 'uyut', 'kilitle', 'iptal'):
        return 'Hata: işlem kapat | yeniden_baslat | oturum_kapat | uyut | kilitle | iptal olmalı.'
    if not IS_WIN:
        return 'Hata: güç işlemleri yalnızca Windows\'ta çalışır.'
    try:
        if islem == 'iptal':
            kod, cikti = _calistir(['shutdown', '/a'])
            return 'Bekleyen kapatma/yeniden başlatma iptal edildi.' if kod == 0 else 'İptal edilecek bekleyen bir kapatma yok.'
        if islem == 'kilitle':
            _calistir(['rundll32.exe', 'user32.dll,LockWorkStation'])
            return 'Ekran kilitlendi.'
        if not onay:
            return ('Henüz yapılmadı: bu işlem açık işleri kaybettirebilir. Kullanıcıya “emin misin?” diye sor; '
                    '“evet” derse aynı çağrıyı onay=true ile tekrarla.')
        if islem == 'uyut':
            _calistir(['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0'])
            return 'Bilgisayar uyku moduna alınıyor.'
        cmd, ne = _GUC[islem]
        if islem == 'oturum_kapat':
            _calistir(cmd)
            return 'Oturum kapatılıyor.'
        sn = max(10, min(int(saniye or 30), 300))
        kod, cikti = _calistir(cmd + [str(sn)])
        if kod != 0:
            return f'Hata: işlem başlatılamadı ({cikti[:120] or kod}).'
        return f'{sn} saniye sonra {ne}. Vazgeçmek için “iptal et” demen yeterli (guc_islemi iptal).'
    except Exception as exc:
        log('ek_paket: güç işlemi hatası', type(exc).__name__, exc)
        return f'Hata: işlem yapılamadı ({type(exc).__name__}).'


# --------------------------------------------------------------------------- Ekran görüntüsü
def _resimler_klasoru() -> Path:
    ev = Path.home()
    for ad in ('OneDrive', 'OneDrive - Personal'):
        p = ev / ad / 'Pictures'
        if not p.exists():
            p = ev / ad / 'Resimler'
        if p.exists():
            return p
    for ad in ('Pictures', 'Resimler'):
        if (ev / ad).exists():
            return ev / ad
    return ev / 'Pictures'


def _tum_ekran():
    """Bütün ekranların (sanal masaüstü) görüntüsü: yalnızca ctypes/GDI + PIL.Image.
    NOT: PIL.ImageGrab exe'de YOK (PyInstaller yalnızca özgün uygulamanın içe aktardıklarını paketledi) → ImportError."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]; user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]; user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]; gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]; gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]; gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]; gdi32.DeleteDC.argtypes = [wintypes.HDC]
    old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))      # PER_MONITOR_V2: gerçek piksel boyutları
    screen = memdc = bmp = None
    try:
        x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        if w <= 0 or h <= 0:
            raise OSError('ekran boyutu okunamadı')
        screen = user32.GetDC(None)
        memdc = gdi32.CreateCompatibleDC(screen)
        bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
        prev = gdi32.SelectObject(memdc, bmp)
        if not gdi32.BitBlt(memdc, 0, 0, w, h, screen, x, y, 0x00CC0020 | 0x40000000):   # SRCCOPY | CAPTUREBLT
            raise OSError('BitBlt başarısız')
        gdi32.SelectObject(memdc, prev)

        class BMI(ctypes.Structure):
            _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                        ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                        ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                        ('biClrImportant', wintypes.DWORD), ('bmiColors', wintypes.DWORD * 3)]
        info = BMI(biSize=40, biWidth=w, biHeight=-h, biPlanes=1, biBitCount=32)
        buf = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(info), 0) != h:
            raise OSError('GetDIBits başarısız')
        return Image.frombuffer('RGB', (w, h), buf.raw, 'raw', 'BGRX', 0, 1).copy()
    finally:
        if bmp:
            gdi32.DeleteObject(bmp)
        if memdc:
            gdi32.DeleteDC(memdc)
        if screen:
            user32.ReleaseDC(None, screen)
        user32.SetThreadDpiAwarenessContext(old)


def _pencere_goruntusu():
    """Uygulamanın kendi (kanıtlanmış) yolu: etkin pencere. (görüntü, hata)"""
    from .actions import win_screen
    bulunan = win_screen.capture()
    if isinstance(bulunan, str):
        return None, bulunan
    return bulunan[0], ''


def ekran_goruntusu(hedef: str = 'tum_ekran') -> str:
    if not IS_WIN:
        return 'Hata: ekran görüntüsü yalnızca Windows\'ta çalışır.'
    img, not_ = None, ''
    try:
        if hedef == 'pencere':
            img, hata = _pencere_goruntusu()
            if img is None:
                return 'Hata: ' + hata
        else:
            try:
                img = _tum_ekran()
            except Exception as exc:                                  # tam ekran olmadıysa etkin pencereye düş
                log('ek_paket: tam ekran görüntüsü olmadı', type(exc).__name__, exc)
                img, hata = _pencere_goruntusu()
                if img is None:
                    return f'Hata: ekran görüntüsü alınamadı ({type(exc).__name__}: {str(exc)[:80]}; pencere yolu da: {hata})'
                not_ = ' (Tam ekran alınamadı; etkin pencerenin görüntüsünü kaydettim.)'
        klasor = _resimler_klasoru() / 'BLOOM Ekran Görüntüleri'
        klasor.mkdir(parents=True, exist_ok=True)
        yol = klasor / ('ekran-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '.png')
        img.save(yol, 'PNG')
    except Exception as exc:
        log('ek_paket: ekran görüntüsü hatası', type(exc).__name__, exc)
        return f'Hata: ekran görüntüsü alınamadı ({type(exc).__name__}: {str(exc)[:100]})'
    return f'Ekran görüntüsü kaydedildi: {yol}{not_}'


# --------------------------------------------------------------------------- Makrolar (Kalliope'nin "synapse"i)
def _makro_yol() -> Path:
    return _ek()._dir() / 'makrolar.json'


def makrolar() -> list[dict]:
    with _L:
        if _S['makrolar'] is None:
            v = _ek()._read_json(_makro_yol(), [])
            _S['makrolar'] = [m for m in v if isinstance(m, dict) and m.get('ad') and isinstance(m.get('adimlar'), list)] if isinstance(v, list) else []
        return _S['makrolar']


def _kaydet() -> None:
    _ek()._write_json(_makro_yol(), makrolar())


def _bul(ad: str) -> dict | None:
    k = _sade(ad)
    if not k:
        return None
    tam = [m for m in makrolar() if _sade(m['ad']) == k or any(_sade(t) == k for t in m.get('tetik', []))]
    if tam:
        return tam[0]
    kismi = [m for m in makrolar() if k in _sade(m['ad']) or any(k in _sade(t) for t in m.get('tetik', []))]
    return kismi[0] if len(kismi) == 1 else None


def _adim_coz(adimlar) -> tuple[list[dict] | None, str]:
    out = []
    reg = _S['reg']
    for n, a in enumerate(adimlar or [], 1):
        if not isinstance(a, dict) or not a.get('arac'):
            return None, f'{n}. adım: "arac" eksik.'
        arac = str(a['arac']).strip()
        if arac in MAKRO_ENGEL:
            return None, f'{n}. adım: “{arac}” makroda kullanılamaz (güvenlik).'
        if reg is not None and arac not in reg.tools:
            return None, f'{n}. adım: “{arac}” diye bir araç yok.'
        p = a.get('parametreler') or {}
        if isinstance(p, str):
            try:
                p = json.loads(p) if p.strip() else {}
            except ValueError:
                return None, f'{n}. adım: parametreler geçerli JSON değil.'
        if not isinstance(p, dict):
            return None, f'{n}. adım: parametreler bir nesne olmalı.'
        out.append({'arac': arac, 'parametreler': p})
    if not out:
        return None, 'En az bir adım gerekli.'
    if len(out) > MAKRO_MAX_ADIM:
        return None, f'En fazla {MAKRO_MAX_ADIM} adım olabilir.'
    return out, ''


def makro_calistir(m: dict) -> str:
    reg = _S['reg']
    if reg is None:
        return 'Hata: araçlar hazır değil.'
    with _L:
        if m['ad'] in _S['calisiyor']:
            return f'“{m["ad"]}” zaten çalışıyor.'
        _S['calisiyor'].add(m['ad'])
    try:
        from .tools.registry import ToolContext
        sonuc = []
        for n, a in enumerate(m['adimlar'], 1):
            try:
                r, ok = reg.call(a['arac'], dict(a['parametreler']), ToolContext())
            except Exception as exc:
                r, ok = f'Hata: {type(exc).__name__}', False
            r = _ek()._clip(r, 160)
            sonuc.append(f'{n}. {a["arac"]}: {r}')
            if not ok or r.startswith('Hata'):
                sonuc.append('→ Hata olduğu için sonraki adımlar atlandı.')
                break
        return f'“{m["ad"]}” çalıştı:\n' + '\n'.join(sonuc)
    finally:
        with _L:
            _S['calisiyor'].discard(m['ad'])


def makro_araci(a: dict, _c=None) -> str:
    islem = (a.get('islem') or 'listele').strip()
    ad = (a.get('ad') or '').strip()
    if islem == 'listele':
        ms = makrolar()
        if not ms:
            return 'Kayıtlı makro yok. “… dediğimde şunu yap” diyerek öğretebilirsin.'
        return 'Makrolar:\n' + '\n'.join(
            f'- {m["ad"]}' + (f' (tetik: {", ".join(m["tetik"])})' if m.get('tetik') else '') +
            ': ' + ' → '.join(x['arac'] for x in m['adimlar']) for m in ms)
    if islem == 'ekle':
        if not ad:
            return 'Hata: makroya bir ad ver.'
        adimlar, hata = _adim_coz(a.get('adimlar'))
        if adimlar is None:
            return 'Hata: ' + hata
        tetik = [str(t).strip() for t in (a.get('tetik') or []) if str(t).strip()][:5]
        with _L:
            ms = makrolar()
            eski = next((m for m in ms if _sade(m['ad']) == _sade(ad)), None)
            yeni = {'ad': ad, 'tetik': tetik, 'adimlar': adimlar, 'olusturma': dt.datetime.now().isoformat(timespec='seconds')}
            if eski is not None:
                ms[ms.index(eski)] = yeni
            else:
                if len(ms) >= 30:
                    return 'Hata: en fazla 30 makro olabilir; birini sil.'
                ms.append(yeni)
            _kaydet()
        return f'Makro {"güncellendi" if eski else "kaydedildi"}: “{ad}” ({len(adimlar)} adım).'
    m = _bul(ad)
    if islem == 'calistir':
        if m is None:
            return f'Hata: “{ad}” adında tek bir makro bulamadım. makro listele ile bak.'
        return makro_calistir(m)
    if islem == 'sil':
        if ad == 'hepsi':
            with _L:
                makrolar().clear()
                _kaydet()
            return 'Tüm makrolar silindi.'
        if m is None:
            return f'Hata: “{ad}” adında tek bir makro bulamadım.'
        with _L:
            makrolar().remove(m)
            _kaydet()
        return f'Makro silindi: “{m["ad"]}”.'
    return 'Hata: işlem ekle | listele | calistir | sil olmalı.'


def istem_blogu() -> str:
    ms = makrolar()
    s = ('[MAKROLAR] Kullanıcı bir işlem dizisini adlandırıp öğretebilir (“akşam rutini dediğimde müziği aç, '
         'yarınki takvimi oku” gibi): makro aracı, islem=ekle. Kayıtlı bir adı ya da tetik cümleyi söylerse '
         'makro calistir ile çalıştır; adımları tek tek kendin yapma. Makroda güç işlemi ve kabuk komutu olamaz.')
    if ms:
        s += '\nKayıtlı makrolar: ' + '; '.join(
            f'{m["ad"]}' + (f' (“{m["tetik"][0]}”)' if m.get('tetik') else '') for m in ms[:15])
    return s


def sayilar() -> dict:
    return {'makro': len(makrolar())}


# --------------------------------------------------------------------------- araç sarmalayıcıları
def arac_vikipedi(a, _c=None):
    return vikipedi(a.get('konu', ''), a.get('dil') or 'tr')


def arac_sozluk(a, _c=None):
    return sozluk(a.get('kelime', ''))


def arac_haber(a, _c=None):
    return haberler(a.get('konu', ''), a.get('kategori', ''), a.get('adet') or 6)


def arac_eposta(a, _c=None):
    return eposta_taslagi(a.get('alici', ''), a.get('konu', ''), a.get('metin', ''), a.get('saglayici') or 'gmail')


def arac_guc(a, _c=None):
    return guc_islemi(a.get('islem', ''), a.get('saniye'), bool(a.get('onay')))


def arac_ekran(a, _c=None):
    return ekran_goruntusu(a.get('hedef') or 'tum_ekran')
