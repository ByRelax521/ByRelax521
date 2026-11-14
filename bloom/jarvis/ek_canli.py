"""BLOOM EK — canlı döküm: söylenen metin SÖYLENİRKEN ekranda belirir.

V4 yalnızca cevap bitince (turn_complete) tek satır yazıyordu; üstelik Gemini sesi gerçek zamandan hızlı üretir, yani o satır
konuşma bitmeden çok önce çıkardı. Burada:
  · Gemini'nin `output_transcription` parçaları ve ses parçalarının SÜRESİ izlenir (ek_bellek.gozle zaten receive() akışını
    dinleyen sarmalayıcıdan geçirir; akışa dokunulmaz).
  · Her metin parçası, ilgili sesin ÇALINMAYA BAŞLAYACAĞI ana göre zamanlanır (ses süresi = bayt / 48000), böylece yazı sesle
    birlikte akar. Ses kapalıysa (yazılı mod) ya da ayar kapalıysa parçalar hemen gösterilir.
  · Kullanıcının konuşması (input_transcription) hemen gösterilir.
  · Kullanıcı lafı keserse yalnızca gerçekten konuşulan kısım "…" ile kalıcı olur.
HUD tarafı: jarvis-ek.js (ekCanli / ekCanliSon). Gerçek satır (J.line) gelince canlı satırın yerini alır.
"""

from __future__ import annotations
import collections
import threading
import time
from .log import log

SES_BAYT_SN = 48000.0        # Gemini Live çıkışı: 24 kHz, 16 bit, mono
PUSH_ARASI = 0.06            # HUD'a en sık bu aralıkla yaz (sn)

_lock = threading.RLock()
_cv = threading.Condition(_lock)
_A = {}
_Y = {}
_thread = {'t': None}


def _simdi() -> float:
    return time.monotonic()


def _ai_sifirla() -> None:
    _A.clear()
    _A.update(full='', shown='', q=collections.deque(), play_end=0.0, ses_arasi=0.0, last_due=0.0, bitti=False,
              bildirildi=True, kesilen='')


def _you_sifirla() -> None:
    _Y.clear()
    _Y.update(text='', son_push=0.0, kirli=False, acik=False)


_ai_sifirla()
_you_sifirla()


# --------------------------------------------------------------------------- ayarlar / HUD
def _acik() -> bool:
    try:
        from . import ek
        return bool(ek.ayar('canli_acik', True))
    except Exception:
        return True


def _senkron() -> bool:
    try:
        from . import ek, ek_ses
        return bool(ek.ayar('canli_senkron', True)) and not ek_ses.sessiz_mi()
    except Exception:
        return True


def _hud(method: str, *args) -> None:
    try:
        from . import ek
        a = ek.app
        if a is not None and ek.hud_ready:
            a.hud.call(method, *args)
    except Exception as exc:
        log('ek_canli: HUD yazılamadı', type(exc).__name__)


# --------------------------------------------------------------------------- akış izleme
def _ses_say(sc, r) -> int:
    n = 0
    try:
        mt = getattr(sc, 'model_turn', None)
        for p in (getattr(mt, 'parts', None) or []):
            d = getattr(getattr(p, 'inline_data', None), 'data', None)
            if isinstance(d, (bytes, bytearray)):
                n += len(d)
    except Exception:
        pass
    return n


def gozle(r) -> None:
    """`session.receive()` akışından geçen her yanıt için çağrılır (ek_bellek.gozle içinden). Hiçbir şeyi değiştirmez."""
    sc = getattr(r, 'server_content', None)
    if not sc or not _acik():
        return
    ot = getattr(getattr(sc, 'output_transcription', None), 'text', None)
    it = getattr(getattr(sc, 'input_transcription', None), 'text', None)
    ses = _ses_say(sc, r)
    kes = bool(getattr(sc, 'interrupted', False))
    bit = bool(getattr(sc, 'turn_complete', False))
    if not (ot or it or ses or kes or bit):
        return
    now = _simdi()
    senk = _senkron()
    with _cv:
        if it:
            _Y['text'] += it
            _Y['acik'] = True
            _Y['kirli'] = True
        if ot or ses:
            if _Y['acik']:                      # model konuşmaya başladı: kullanıcının canlı satırı biter
                _Y['acik'] = False
                _hud('ekCanliSon', 'you')
                _you_sifirla()
            if _A['bitti']:
                _flush_ai(now)                  # önceki cevap hâlâ akıyorsa hemen tamamla
                _ai_sifirla()
        if ses:
            sure = ses / SES_BAYT_SN
            _A['play_end'] = max(_A['play_end'], now) + sure
            _A['ses_arasi'] += sure
            _A['bildirildi'] = False
        if ot:
            _A['full'] += ot
            if senk:
                start = _A['play_end'] - _A['ses_arasi'] if _A['ses_arasi'] > 0 else max(_A['play_end'], now)
                due = max(start, _A['last_due'], now)
            else:
                due = now
            _A['last_due'] = due
            _A['ses_arasi'] = 0.0
            _A['q'].append((due, ot))
            _A['bildirildi'] = False
        if kes:
            _kes(now)
        if bit:
            if _Y['acik']:
                _hud('ekCanliSon', 'you')
                _you_sifirla()
            _A['bitti'] = True
            _A['bildirildi'] = not (_A['q'] or _A['shown'])
            if not _A['q'] and _A['shown']:
                _bildir_son()
        _cv.notify_all()
    _baslat()


def _bildir_son() -> None:
    if not _A['bildirildi']:
        _A['bildirildi'] = True
        _hud('ekCanliSon', 'ai', None, None)


def _flush_ai(now: float) -> None:
    """Kuyrukta bekleyen her şeyi hemen göster ve bitir (yeni cevap başlarken)."""
    degisti = False
    while _A['q']:
        _A['shown'] += _A['q'].popleft()[1]
        degisti = True
    if degisti and _A['shown'].strip():
        _hud('ekCanli', 'ai', _A['shown'])
    _bildir_son()


def _kes(now: float) -> None:
    """Kullanıcı konuşurken cevap kesildi: yalnızca o ana kadar GÖSTERİLEN kısım kalıcı olur."""
    gosterilen = _A['shown']
    ham = _A['full']                      # üretilmiş her şey: V4'ün gerçek satırı bunu da içerir (JS başından atar)
    _A['q'].clear()
    _hud('ekCanliSon', 'ai', (gosterilen.rstrip() + '…') if gosterilen.strip() else '', ham)
    # yeni parçalar boş canlı satıra yazılır
    _A['kesilen'] += ham
    _A['full'] = ''
    _A['shown'] = ''
    _A['play_end'] = 0.0
    _A['ses_arasi'] = 0.0
    _A['last_due'] = 0.0
    _A['bildirildi'] = True
    _A['bitti'] = False


# --------------------------------------------------------------------------- yazıcı iş parçacığı
def _tik(now: float | None = None) -> float:
    """Zamanı gelen parçaları HUD'a yazar; bir sonraki uyanma süresini (sn) döner. (Test edilebilsin diye ayrı.)"""
    now = _simdi() if now is None else now
    with _cv:
        degisti = False
        while _A['q'] and _A['q'][0][0] <= now:
            _A['shown'] += _A['q'].popleft()[1]
            degisti = True
        if _A['q']:
            sonraki = max(0.02, _A['q'][0][0] - now)
        else:
            sonraki = 0.5
        if degisti and _A['shown'].strip():
            _hud('ekCanli', 'ai', _A['shown'])
        if not _A['q'] and _A['bitti'] and _A['shown'] and not _A['bildirildi']:
            _bildir_son()
        if _Y['kirli'] and now - _Y['son_push'] >= PUSH_ARASI:
            _Y['kirli'] = False
            _Y['son_push'] = now
            if _Y['text'].strip():
                _hud('ekCanli', 'you', _Y['text'])
        elif _Y['kirli']:
            sonraki = min(sonraki, PUSH_ARASI)
        return sonraki


def _dongu() -> None:
    while True:
        try:
            with _cv:
                bekle = _tik()
                _cv.wait(timeout=bekle)
        except Exception as exc:
            log('ek_canli: yazıcı hatası', type(exc).__name__, exc)
            time.sleep(1)


def _baslat() -> None:
    with _lock:
        if _thread['t'] is not None and _thread['t'].is_alive():
            return
        t = threading.Thread(target=_dongu, daemon=True, name='ek-canli')
        _thread['t'] = t
        t.start()


def durum() -> dict:
    with _lock:
        return {'acik': _acik(), 'senkron': _senkron(), 'bekleyen': len(_A['q']), 'gosterilen': len(_A['shown'])}
