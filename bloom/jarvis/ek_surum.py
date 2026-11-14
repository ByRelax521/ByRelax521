"""BLOOM EK — sürüm, özellik listesi ve günlük (log) görünümü.

* Yazı kutusuna `--version` yazınca BLOOM sürümünü söyler; `--help` yapabildiği her şeyi, `--log` günlüğün son satırlarını verir.
  Bu komutlar modele GİTMEZ (yerelde cevaplanır): ağ/kota harcamaz, model uydurup yanlış sürüm söyleyemez.
* Özellik listesi KAYITLI ARAÇLARDAN çıkarılır (registry): bu bilgisayarda gerçekten çalışabilen araçlar. Elle yazılmış bir liste
  gerçekle ayrışabilirdi; bu liste her açılışta güncel olur.
* Mark 2 web ekranındaki LOG düğmesi aynı veriyi ek_web üzerinden okur.
* Günlükten gizli bilgi sızmaması için anahtar benzeri diziler maskelenir; YAYIN modu açıkken günlük gösterilmez.
"""
from __future__ import annotations
import platform
import re
import sys
import threading
from pathlib import Path
from .log import log

SURUM = '3.12.1'
ESKI_AD = 'JARVIS'

GIZLI = {'secret_topic', 'final_choice', 'offer_disable_others', 'show_creator'}
KATEGORILER = [
    ('Zaman ve planlama', ['set_timer', 'cancel_timer', 'timer_status', 'stopwatch', 'pomodoro', 'get_calendar_events', 'add_calendar_event',
                           'delete_calendar_event', 'get_reminders', 'add_reminder', 'delete_reminder', 'complete_reminder', 'fikir', 'sonra_yap']),
    ('Notlar ve bellek', ['add_note', 'list_notes', 'delete_note', 'clear_notes', 'save_memory', 'delete_memory', 'hafiza_ara', 'onemli_kaydet',
                          'ders_yonet', 'pano_oku', 'ozetle']),
    ('Bilgi ve arama', ['web_search', 'arastir', 'vikipedi', 'sozluk', 'haberler', 'get_weather', 'show_on_map', 'get_directions', 'konum_ayarla']),
    ('Bilgisayar ve uygulamalar', ['open_app', 'close_app', 'find_files', 'read_file', 'create_file', 'sys_info', 'shell_run', 'browser_control',
                                   'guc_islemi', 'ekran', 'analyze_screen', 'ekran_goruntusu', 'toggle_webcam', 'kod', 'eposta_taslagi',
                                   'send_whatsapp_message', 'save_whatsapp_contact']),
    ('Müzik ve medya', ['play_media', 'media_control', 'spotify']),
    ('Zekâ ve otomasyon', ['konsey', 'anla', 'hermes', 'isler', 'mcp', 'yetenek_oku', 'yetenek_yonet', 'gelisim', 'kendi_kod', 'makro']),
    ('Gizlilik ve ayar', ['yayin', 'ses_ayari', 'set_microphone', 'go_to_sleep', 'quit_app', 'open_chip_picker']),
]
EKRAN_KOMUTLARI = [
    ('--version', 'sürümü söyler'),
    ('--help', 'yapabildiği her şeyin listesi'),
    ('--log', 'günlüğün son satırları'),
]
DIGER = 'Diğer'
_L = threading.RLock()


# --------------------------------------------------------------------------- araçlar
def _kayit():
    from .tools import registry
    return registry


def _ilk_cumle(t: str, n: int = 120) -> str:
    t = re.sub(r'\s+', ' ', str(t or '')).strip()
    m = re.search(r'(?<=[.!?])\s', t)          # yalnız cümle sonu: parantez/iki nokta/örnek tırnağında kesme
    k = (t[:m.start()] if m else t).strip()
    return (k[:n - 1].rstrip() + '…') if len(k) > n else k


def ozellikler_veri() -> list[dict]:
    """[{kategori, araclar:[{ad, aciklama}]}] — bu bilgisayarda gerçekten kullanılabilen araçlar."""
    try:
        araclar = {t.name: t for t in _kayit().available() if t.name not in GIZLI}
    except Exception as exc:
        log('ek_surum: araç listesi', type(exc).__name__, exc)
        araclar = {}
    out, gorulen = [], set()
    for kat, adlar in KATEGORILER:
        liste = [{'ad': a, 'aciklama': _ilk_cumle(araclar[a].description)} for a in adlar if a in araclar]
        gorulen.update(a for a in adlar if a in araclar)
        if liste:
            out.append({'kategori': kat, 'araclar': liste})
    kalan = [{'ad': a, 'aciklama': _ilk_cumle(t.description)} for a, t in araclar.items() if a not in gorulen]
    if kalan:
        out.append({'kategori': DIGER, 'araclar': kalan})
    return out


def arac_sayisi() -> int:
    return sum(len(k['araclar']) for k in ozellikler_veri())


def ozellikler_metni(ayrintili: bool = False) -> str:
    v = ozellikler_veri()
    if not v:
        return 'Araç listesi şu an okunamadı (günlükte ayrıntı var: --log).'
    satir = [f'BLOOM {SURUM} — yapabildiklerim ({sum(len(k["araclar"]) for k in v)} araç):']
    for k in v:
        satir.append('')
        satir.append(k['kategori'].upper())
        for a in k['araclar']:
            satir.append(f'  • {a["ad"]} — {a["aciklama"]}' if ayrintili else f'  • {a["ad"]}')
    satir += ['', 'Yazı kutusu komutları: ' + ' · '.join(f'{c} ({d})' for c, d in EKRAN_KOMUTLARI),
              'Konuşarak ya da yazarak doğal cümleyle iste; aracı kendim seçerim.']
    return '\n'.join(satir)


# --------------------------------------------------------------------------- sürüm
def bilgi() -> dict:
    ek_sur = ''
    try:
        from . import ek
        ek_sur = str(getattr(ek, 'VERSION_EK', ''))
    except Exception:
        pass
    ekran = ''
    try:
        from . import ek_web
        ekran = 'Mark II web ekranı' if ek_web.dosyalar() else 'Mark II katmanı'
    except Exception:
        ekran = 'Mark II katmanı'
    try:
        from . import paths
        os_ad = 'Windows' if paths.IS_WIN else platform.system()
    except Exception:
        os_ad = platform.system()
    return {'surum': SURUM, 'ad': 'BLOOM', 'eski_ad': ESKI_AD, 'ekran': ekran, 'beyin': 'Gemini Live', 'ek': ek_sur,
            'python': platform.python_version(), 'sistem': os_ad, 'arac': arac_sayisi()}


def surum_metni() -> str:
    b = bilgi()
    return (f"BLOOM {b['surum']} (eski adı {b['eski_ad']})\n"
            f"Ekran: {b['ekran']} · Beyin: {b['beyin']} · Sistem: {b['sistem']} · Python {b['python']}\n"
            f"Kullanabildiğim araç sayısı: {b['arac']}. Hepsi için: --help · Günlük için: --log")


# --------------------------------------------------------------------------- günlük
_MASKE = [
    (re.compile(r'AIza[0-9A-Za-z_\-]{20,}'), 'AIza…'),
    (re.compile(r'\b(sk|rk|ghp|gho|xox[bap])[-_][0-9A-Za-z_\-]{16,}'), r'\1-…'),
    (re.compile(r'(?i)\b(bearer|api[_-]?key|token|secret|password|parola|şifre)\b(\s*[:=]\s*|\s+)[^\s,;"\']{6,}'), r'\1\2•••'),
    (re.compile(r'(?i)(authorization:\s*)\S+(\s+\S+)?'), r'\1•••'),
]


def maskele(t: str) -> str:
    for r, y in _MASKE:
        t = r.sub(y, t)
    return t


def log_son(n: int = 200) -> list[str]:
    """Günlüğün son n satırı (anahtar benzeri diziler maskeli). YAYIN modunda boş + uyarı."""
    n = max(1, min(int(n or 200), 1000))
    try:
        from . import ek_yayin
        if ek_yayin.acik():
            return ['(YAYIN modu açık: günlük gizlendi. Yayın modunu kapatınca görünür.)']
    except Exception:
        pass
    try:
        from . import paths
        p = Path(paths.LOG_FILE)
        if not p.is_file():
            return ['(günlük dosyası henüz yok)']
        boyut = p.stat().st_size
        with p.open('rb') as f:
            f.seek(max(0, boyut - 400_000))
            ham = f.read().decode('utf-8', 'replace')
        satirlar = ham.splitlines()
        if boyut > 400_000 and satirlar:
            satirlar = satirlar[1:]            # kesilmiş ilk satır
        return [maskele(s) for s in satirlar[-n:]] or ['(günlük boş)']
    except Exception as exc:
        return [f'(günlük okunamadı: {type(exc).__name__})']


def log_metni(n: int = 25) -> str:
    return 'Günlüğün son satırları:\n' + '\n'.join(log_son(n))


# --------------------------------------------------------------------------- yazı kutusu komutları
_KOMUT = [
    (re.compile(r'(?i)^\s*(--?version|-v|--sürüm|--surum|--sürüm|--ver)\s*$'), lambda: surum_metni()),
    (re.compile(r'(?i)^\s*(--?help|-h|--yardım|--yardim|--özellikler|--ozellikler|--features)\s*$'), lambda: ozellikler_metni(False)),
    (re.compile(r'(?i)^\s*(--?log|--günlük|--gunluk|--logs)\s*$'), lambda: log_metni(25)),
]


def komut(metin: str) -> str | None:
    """`--version` gibi bir komutsa cevap metnini, değilse None döner."""
    t = str(metin or '')
    if len(t) > 40:
        return None
    for r, f in _KOMUT:
        if r.match(t):
            try:
                return f()
            except Exception as exc:
                log('ek_surum: komut hatası', type(exc).__name__, exc)
                return 'Bu bilgi şu an alınamadı (günlükte ayrıntı var).'
    return None


def kur(a) -> None:
    """Yazılan metni modele gitmeden önce yakalar (idempotent)."""
    with _L:
        b = getattr(a, 'brain', None)
        if b is None or getattr(b, '_ek_surum', False):
            return
        asil = b.send_text

        def send_text(text, *args, **kw):
            c = komut(text)
            if c is None:
                return asil(text, *args, **kw)
            log('ek_surum: yerel komut', str(text).strip()[:20])
            try:
                a.hud.call('line', 'ai', c)
            except Exception as exc:
                log('ek_surum: cevap yazılamadı', type(exc).__name__)
            return None

        try:
            b.send_text = send_text
            b._ek_surum = True
        except Exception as exc:
            log('ek_surum: kurulamadı', type(exc).__name__, exc)
