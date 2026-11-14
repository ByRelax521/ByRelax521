"""BLOOM EK — ses modu: odak/medya algısı, "Hey Bloom" kapısı, yazılı mod, mikrofon rozeti onarımı.

Üç mod (kullanıcıya üst çubukta bir yazıyla gösterilir):
  serbest : BLOOM penceresi öndeyken ve arkada ses çalmıyorsa mikrofon her zamanki gibi serbest.
  cagri   : başka bir pencere öndeyken (BLOOM odakta değil) yalnızca "Hey Bloom" deyince dinler.
  yazili  : arkada Spotify/video gibi bir ses çalıyorsa BLOOM'un SESİ kapalıdır (cevap sohbette yazılı görünür,
            komutlar yine yapılır) ve dinlemek için yine "Hey Bloom" gerekir (müziği söz sanmasın).

Kapı, V4'ün işlevlerini değiştirmeden çalışma anında takılır: `GeminiLiveBrain._pump_mic` oturumun
`send_realtime_input` işlevini (örnek düzeyinde) sarar; kapalıyken ses Gemini'ye GİTMEZ, yalnızca yerelde
dedektöre girer. Dedektör yüklenemezse kapı hiç kapanmaz (eski davranış).

Ayrıca: mikrofon gerçekten ses veriyorken ekranda takılı kalan "MİKROFON …" rozeti kaldırılır.
"""

from __future__ import annotations
import collections
import ctypes
import os
import sys
import threading
import time
from . import paths
from .log import log

IS_WIN = bool(getattr(paths, 'IS_WIN', False))
HASSASIYET = {'yuksek': 0.30, 'orta': 0.42, 'dusuk': 0.65}
UYANIK_SN = 12.0          # "Hey Bloom"tan sonra konuşmaya başlaman için
KONUSMA_SN = 6.0          # konuşurken kapı bu kadar açık tutulur
CEVAP_SN = 10.0           # BLOOM konuştuktan sonra cevap verebilmen için
ONCEKI_SN = 2.4           # kapalıyken tutulan geçmiş ses (uyandırma sözünün kendisi de modele gider)
MEDYA_ESIK = 0.012
_lock = threading.RLock()
_S = {
    'odak': True, 'medya': False, 'mod': 'serbest', 'acik_until': 0.0, 'wake_t': 0.0, 'skor': 0.0,
    'ses_t': 0.0, 'kayit_t': 0.0, 'oncesi': collections.deque(), 'oncesi_sn': 0.0, 'cfg': {},
    'odak_zorla': None, 'medya_zorla': None, 'izleyici': False, 'kapali_blok': 0, 'wake_sayi': 0,
    'son_mod_hud': '', 'olcer_hata': '',
}


MOD_NOTU = {
    'yazili': '(Sistem notu: arkada müzik/video çalıyor; SESİN KAPALI — cevabın yalnızca ekranda yazılı görünür. Komutları yine yap, '
              'cevabı kısa ve öz yaz; müziğe/videoya kendiliğinden dokunma. Kullanıcı seni yalnızca "Hey Bloom" diyerek çağırır.)',
    'cagri': '(Sistem notu: kullanıcı başka bir pencerede çalışıyor; yalnızca "Hey Bloom" deyince konuşuyor. Kısa cevap ver.)',
    'serbest': '(Sistem notu: kullanıcı BLOOM penceresine döndü ve arkada ses yok; sesli, normal konuşmaya dönebilirsin.)',
}


def _ek():
    from . import ek
    return ek


# --------------------------------------------------------------------------- ayarlar (önbellek)
def _cfg_yenile() -> None:
    try:
        ek = _ek()
        s = ek._state()
    except Exception:
        s = {}
    _S['cfg'] = {
        'uyandir': bool(s.get('uyandir_acik', True)),
        'yazili': bool(s.get('yazili_mod', True)),
        'hassasiyet': s.get('uyandir_hassasiyet') if s.get('uyandir_hassasiyet') in HASSASIYET else 'orta',
    }


def cfg(k: str):
    c = _S['cfg']
    if not c:
        _cfg_yenile()
        c = _S['cfg']
    return c.get(k)


def esik() -> float:
    return HASSASIYET.get(cfg('hassasiyet'), 0.42)


def dedektor():
    from . import ek_uyandir
    return ek_uyandir.dedektor()


# --------------------------------------------------------------------------- pencere odağı
def pencere_odakta() -> bool:
    if _S['odak_zorla'] is not None:
        return bool(_S['odak_zorla'])
    if not IS_WIN:
        return True
    try:
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        if not h:
            return False
        pid = ctypes.c_ulong(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        return int(pid.value) == os.getpid()
    except Exception:
        return True


# --------------------------------------------------------------------------- arkada ses (Core Audio tepe ölçer)
_IID_METER = 'C02216F6-8C67-4B5B-9D00-D008E73E0064'


class Olcer:
    """Varsayılan hoparlörün IAudioMeterInformation'ı: şu an bilgisayardan ses çıkıyor mu (0..1 tepe)."""

    def __init__(self) -> None:
        self.objs = []
        self.meter = None
        self.owned = False
        self.t = 0.0

    def ac(self) -> None:
        from .actions import win_media as wm
        self.kapat()
        self.owned = wm._ole32.CoInitializeEx(None, 2) in (0, 1)
        enum, device, meter = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if wm._ole32.CoCreateInstance(ctypes.byref(wm._guid(wm._CLSID_ENUMERATOR)), None, 23,
                                      ctypes.byref(wm._guid(wm._IID_ENUMERATOR)), ctypes.byref(enum)) or not enum.value:
            raise OSError('ses aygıtları okunamadı')
        self.objs.append(enum)
        if wm._method(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(0, 1, ctypes.byref(device)) or not device.value:
            raise OSError('hoparlör yok')
        self.objs.append(device)
        from ctypes import wintypes
        if wm._method(device, 3, ctypes.POINTER(wm._GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                ctypes.byref(wm._guid(_IID_METER)), 23, None, ctypes.byref(meter)) or not meter.value:
            raise OSError('ses ölçeri açılamadı')
        self.objs.append(meter)
        self.meter = meter
        self.t = time.monotonic()

    def tepe(self) -> float:
        from .actions import win_media as wm
        if self.meter is None or time.monotonic() - self.t > 90:
            self.ac()
        val = ctypes.c_float()
        if wm._method(self.meter, 3, ctypes.POINTER(ctypes.c_float))(ctypes.byref(val)):
            raise OSError('tepe okunamadı')
        return float(val.value)

    def kapat(self) -> None:
        try:
            from .actions import win_media as wm
            for o in reversed(self.objs):
                wm._method(o, 2)()
        except Exception:
            pass
        self.objs, self.meter = [], None


def _kendi_sesim() -> bool:
    """BLOOM'un kendi sesi çalıyorsa ölçüme katılmaz."""
    try:
        br = _ek().app.brain
        return bool(getattr(br, '_speaking', False)) or time.monotonic() - float(getattr(br, '_last_audio', 0.0)) < 1.6
    except Exception:
        return False


class MedyaKarar:
    """Son 8 örnekten (4 sn) histerezisli karar: ≥5 sesli → çalıyor, ≤1 sesli → çalmıyor."""

    def __init__(self) -> None:
        self.son = collections.deque(maxlen=8)
        self.durum = False

    def ekle(self, tepe: float) -> bool:
        self.son.append(tepe > MEDYA_ESIK)
        n = sum(self.son)
        if not self.durum and len(self.son) >= 6 and n >= 5:
            self.durum = True
        elif self.durum and n <= 1:
            self.durum = False
        return self.durum


# --------------------------------------------------------------------------- mod
def mod() -> str:
    if _S['medya_zorla'] is not None:
        medya = bool(_S['medya_zorla'])
    else:
        medya = _S['medya']
    if medya and cfg('yazili'):
        return 'yazili'
    if medya and not cfg('yazili'):
        return 'cagri' if cfg('uyandir') else 'serbest'
    odak = _S['odak'] if _S['odak_zorla'] is None else bool(_S['odak_zorla'])
    if not odak and cfg('uyandir'):
        return 'cagri'
    return 'serbest'


def kapi_gerekli() -> bool:
    return cfg('uyandir') and mod() in ('cagri', 'yazili') and bool(dedektor().hazir)


def sessiz_mi() -> bool:
    return mod() == 'yazili'


def durum() -> dict:
    d = dedektor()
    return {'mod': mod(), 'odak': bool(_S['odak']), 'medya': bool(_S['medya']), 'uyandir_acik': bool(cfg('uyandir')),
            'uyandir_var': bool(d.hazir), 'uyandir_hata': '' if d.hazir else (d.hata or ''),
            'yazili_mod': bool(cfg('yazili')), 'hassasiyet': cfg('hassasiyet'),
            'acik': time.monotonic() < _S['acik_until'], 'uyanma_sayisi': int(_S['wake_sayi'])}


# --------------------------------------------------------------------------- kapı
def _tepe_oran(x) -> float:
    try:
        import numpy as np
        return float(np.abs(x).max()) / 32768.0 if len(x) else 0.0
    except Exception:
        return 0.0


def _cevap_penceresi(now: float) -> bool:
    try:
        br = _ek().app.brain
        if getattr(br, '_speaking', False):
            return True
        return now - float(getattr(br, '_last_audio', 0.0)) < CEVAP_SN
    except Exception:
        return False


def _blob_pcm(blob):
    if blob is None:
        return b''
    if isinstance(blob, dict):
        return blob.get('data') or b''
    return getattr(blob, 'data', b'') or b''


def kapi_ses(pcm: bytes, now: float | None = None) -> tuple[str, list]:
    """Bir mikrofon parçası için karar. ('gonder', [önceki parçalar]) ya da ('birak', [])."""
    now = time.monotonic() if now is None else now
    try:
        import numpy as np
        x = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype=np.int16)
    except Exception:
        return 'gonder', []
    zirve = _tepe_oran(x)
    if zirve * 32768.0 > 3:
        if _S['ses_t'] == 0.0:
            _mic_kaniti()
        _S['ses_t'] = now
    if not kapi_gerekli():
        _S['oncesi'].clear()
        _S['oncesi_sn'] = 0.0
        return 'gonder', []
    if now < _S['acik_until']:
        if zirve > 0.035:
            _S['acik_until'] = max(_S['acik_until'], now + KONUSMA_SN)
        return 'gonder', []
    if _cevap_penceresi(now):
        return 'gonder', []
    # kapalı: yerelde dinle
    d = dedektor()
    skor = d.besle(pcm)
    _S['skor'] = skor
    sn = len(pcm) / 2 / 16000.0
    _S['oncesi'].append((pcm, sn))
    _S['oncesi_sn'] += sn
    while _S['oncesi'] and _S['oncesi_sn'] > ONCEKI_SN:
        _S['oncesi_sn'] -= _S['oncesi'].popleft()[1]
    _S['kapali_blok'] += 1
    if skor >= esik() and now - _S['wake_t'] > 1.5:
        _S['wake_t'] = now
        _S['wake_sayi'] += 1
        _S['acik_until'] = now + UYANIK_SN
        onceki = [p for p, _ in _S['oncesi']]
        _S['oncesi'].clear()
        _S['oncesi_sn'] = 0.0
        d.sifirla()
        log(f'ek: "Hey Bloom" duyuldu (skor {skor:.2f}, mod {mod()})')
        try:
            _ek()._hud('ekUyandi')
        except Exception:
            pass
        return 'gonder', onceki[:-1]        # son parça çağıranın elindeki
    return 'birak', []


def _oturumu_sar(oturum) -> bool:
    if getattr(oturum, '_ek_ses_sarili', False):
        return True
    orig = oturum.send_realtime_input

    async def gonder(*a, **kw):
        blob = kw.get('audio')
        if blob is None:
            return await orig(*a, **kw)
        try:
            karar, onceki = kapi_ses(_blob_pcm(blob))
        except Exception as exc:
            log('ek: ses kapısı hatası', type(exc).__name__, exc)
            return await orig(*a, **kw)
        if karar == 'birak':
            return None
        if onceki:
            mime = getattr(blob, 'mime_type', None) or 'audio/pcm;rate=16000'
            try:
                from google.genai import types
                for p in onceki:
                    await orig(audio=types.Blob(data=p, mime_type=mime))
            except Exception as exc:
                log('ek: önceki ses gönderilemedi', type(exc).__name__, exc)
        return await orig(*a, **kw)

    try:
        oturum.send_realtime_input = gonder
        oturum._ek_ses_sarili = True
        return True
    except Exception as exc:
        log('ek: oturum sarılamadı (ses kapısı kapalı)', type(exc).__name__, exc)
        return False


# --------------------------------------------------------------------------- mikrofon kanıtı / rozet onarımı
def _mic_kaniti() -> None:
    """Mikrofondan GERÇEK ses geldi: bunu hatırla (Windows kayıt defteri 'Deny' dese bile mikrofon çalışıyor demektir)."""
    try:
        ek = _ek()
        t = float(ek.ayar('mic_calisti', 0) or 0)
        if time.time() - t > 86400:
            ek.ayar_yaz('mic_calisti', time.time())
    except Exception:
        pass


def _mic_kaniti_var() -> bool:
    if _S['ses_t'] > 0:
        return True
    try:
        t = float(_ek().ayar('mic_calisti', 0) or 0)
        return t > 0 and time.time() - t < 60 * 86400
    except Exception:
        return False


def rozet_onar() -> bool:
    """Mikrofon ses veriyorsa ve ekranda hata rozeti duruyorsa kaldırır."""
    try:
        br = _ek().app.brain
        if getattr(br, '_mic_problem', '') and _S['ses_t'] and time.monotonic() - _S['ses_t'] < 3.0:
            log('ek: mikrofon ses veriyor; takılı kalan rozet kaldırılıyor (' + str(br._mic_problem) + ')')
            br._mic_problem = ''
            br._mic_fails = 0
            _ek().app.on_mic_status('ok', '')
            return True
    except Exception as exc:
        log('ek: rozet onarılamadı', type(exc).__name__, exc)
    return False


# --------------------------------------------------------------------------- izleyici iş parçacığı
def _izle() -> None:
    karar = MedyaKarar()
    olcer = Olcer() if IS_WIN else None
    t_cfg = 0.0
    d = dedektor()
    threading.Thread(target=d.yukle, daemon=True, name='ek-uyandir-yukle').start()
    while True:
        try:
            now = time.monotonic()
            if now - t_cfg > 2.0:
                t_cfg = now
                _cfg_yenile()
            _S['odak'] = pencere_odakta()
            if _S['medya_zorla'] is None and olcer is not None:
                if not _kendi_sesim():
                    try:
                        _S['medya'] = karar.ekle(olcer.tepe())
                        _S['olcer_hata'] = ''
                    except Exception as exc:
                        if str(exc) != _S['olcer_hata']:
                            _S['olcer_hata'] = str(exc)
                            log('ek: ses ölçülemedi', type(exc).__name__, exc)
                        olcer.kapat()
            m = mod()
            if m != _S['son_mod_hud']:
                log(f'ek: ses modu {_S["son_mod_hud"] or "-"} → {m} (odak={_S["odak"]}, medya={_S["medya"]})')
                onceki = _S['son_mod_hud']
                _S['son_mod_hud'] = m
                try:
                    _ek()._hud_durum()
                except Exception:
                    pass
                not_ = MOD_NOTU.get(m) if (onceki or m != 'serbest') else None
                if not_:
                    try:
                        _ek()._stage(not_)
                    except Exception:
                        pass
            rozet_onar()
        except Exception as exc:
            log('ek: ses izleyici hatası', type(exc).__name__, exc)
        time.sleep(0.5)


def baslat() -> None:
    with _lock:
        if _S['izleyici']:
            return
        _S['izleyici'] = True
    threading.Thread(target=_izle, daemon=True, name='ek-ses').start()


# --------------------------------------------------------------------------- V4'e takma
_sar_lock = threading.Lock()


def beyni_sar() -> bool:
    try:
        from .brain import gemini_live as gl
        from . import permissions
        B = gl.GeminiLiveBrain
        with _sar_lock:
            if getattr(B, '_ek_ses_sarili', False):
                return True
            orig_mic = B._pump_mic
            orig_louder = B._louder

            async def pump_mic(self, session):
                try:
                    _oturumu_sar(session)
                except Exception as exc:
                    log('ek: pump_mic sarılamadı', type(exc).__name__, exc)
                return await orig_mic(self, session)

            def louder(self, pcm):
                if sessiz_mi():
                    # Ses kapalı: sessiz ama boş olmayan kısa bir parça (yazılı döküm aynen sürer; mikrofon, hiç
                    # duyulmayacak bir cevabın süresi boyunca tutulmasın diye 8 kat kısa).
                    return bytes(max(2, (len(pcm) // 8) // 2 * 2))
                return orig_louder(self, pcm)

            B._pump_mic = pump_mic
            B._louder = louder
            orig_status = permissions.media_status

            def media_status(kind):
                r = orig_status(kind)
                try:
                    if kind == 'audio' and r == 'denied' and _mic_kaniti_var():
                        return 'granted'
                except Exception:
                    pass
                return r

            permissions.media_status = media_status
            orig_silent = B._warn_silent

            def warn_silent(self, mic, zeros):
                if zeros:
                    _S['ses_t'] = 0.0
                    try:
                        _ek().ayar_yaz('mic_calisti', 0)
                    except Exception:
                        pass
                return orig_silent(self, mic, zeros)

            B._warn_silent = warn_silent
            try:
                ek = _ek()
                if ek.ayar('mic_calisti', None) is None:
                    # İlk açılış: kullanıcı mikrofonunun çalıştığını bildirdi; Windows kaydı "Deny" gösterse bile
                    # sahte "ERİŞİLEMİYOR" rozeti/ayar sayfası açılmasın. Gerçekten sessizse _warn_silent bunu siler.
                    ek.ayar_yaz('mic_calisti', time.time())
            except Exception:
                pass
            B._ek_ses_sarili = True
        baslat()
        log('ek: ses modu etkin (odak/medya/uyandırma)')
        return True
    except Exception as exc:
        log('ek: ses modu kurulamadı', type(exc).__name__, exc)
        return False
