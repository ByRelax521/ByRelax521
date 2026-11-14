"""bloom — YAYIN MODU: canlı yayında / ekran paylaşırken kişisel bilgileri SAHTESİYLE değiştirir.

Açıkken kategori kategori (her biri ayrı açılıp kapanır):
  konum    ekranda, haritada, hava panelinde ve asistanın sözünde konum SAHTE bir şehir olur (hazır liste ya da yazdığın yer).
  hava     hava durumu sahte şehrin havası olur (yalnız bu açıksa gerçek konum yazıları olduğu gibi kalır).
  kisiler  rehber/WhatsApp adları takma adla, telefon numaraları ••• ile görünür; asistan takma adı söyler.
           Sen "Ayşe'ye yaz" dediğinde takma ad GERÇEK kişiye çevrilir: işler yine doğru kişiye gider.
  hafiza   asistana kişisel hafıza verilmez, Ayarlar › Hafıza boş görünür (sahte DEĞİL, gizli).
  fikir    Fikir Alanım DEMO verisiyle açılır; gerçek verin diskte aynen durur, yayındaki düzenlemeler diske YAZILMAZ.
  kimlik   adın, Windows kullanıcı adın ve bilgisayar adın sahtesiyle değişir (dosya yollarındaki kullanıcı adı dahil).

Nasıl çalışır (üç sınır):
  1) HUD'a giden her metin (Hud.call)   → gerçek değerler sahteyle değiştirilir.
  2) Modele giden her şey                → araç sonuçları, hafıza bloğu, konum bloğu sahte/boş; araç ARGÜMANLARI geri çevrilir.
  3) Konum kaynağı (geo.chosen)          → hava/harita/"neredeyim" hep sahte yeri kullanır; gerçek ayarın üstüne YAZILMAZ.
Gerçek veriler hiçbir zaman sahteyle ezilmez (ayar dosyaları, hafıza, Fikir verisi değişmez).

DÜRÜST SINIRLAR: Mikrofona söylediğin gerçek ad/yer yayında DUYULUR (asistan duyduğunu tekrarlayabilir): yayında takma adı kullan.
Ekranda başka program/pencere (tarayıcı, bildirim) bu modun kapsamında DEĞİL. Metin eşleştirmesi ad listesine dayanır: listede
olmayan bir ad/yer olduğu gibi görünür. Açıldığında asistan oturumu yenilenir (talimat yeniden kurulur).
"""

from __future__ import annotations
import getpass
import hashlib
import os
import re
import socket
import threading
import time
from .log import log

KATEGORILER = ('konum', 'hava', 'kisiler', 'hafiza', 'fikir', 'kimlik')
ETIKET = {'konum': 'Konum', 'hava': 'Hava durumu', 'kisiler': 'Kişiler ve numaralar', 'hafiza': 'Hafıza',
          'fikir': 'Fikir Alanım', 'kimlik': 'Ad ve bilgisayar adı'}
YER_HAZIR = {
    'Lizbon': {'label': 'Lizbon', 'lat': 38.7223, 'lon': -9.1393, 'zoom': 12, 'country': 'Portekiz'},
    'Viyana': {'label': 'Viyana', 'lat': 48.2082, 'lon': 16.3738, 'zoom': 12, 'country': 'Avusturya'},
    'Amsterdam': {'label': 'Amsterdam', 'lat': 52.3676, 'lon': 4.9041, 'zoom': 12, 'country': 'Hollanda'},
    'Kopenhag': {'label': 'Kopenhag', 'lat': 55.6761, 'lon': 12.5683, 'zoom': 12, 'country': 'Danimarka'},
    'Prag': {'label': 'Prag', 'lat': 50.0755, 'lon': 14.4378, 'zoom': 12, 'country': 'Çekya'},
    'Oslo': {'label': 'Oslo', 'lat': 59.9139, 'lon': 10.7522, 'zoom': 12, 'country': 'Norveç'},
    'Helsinki': {'label': 'Helsinki', 'lat': 60.1699, 'lon': 24.9384, 'zoom': 12, 'country': 'Finlandiya'},
    'Dublin': {'label': 'Dublin', 'lat': 53.3498, 'lon': -6.2603, 'zoom': 12, 'country': 'İrlanda'},
}
VARSAYILAN = {'acik': False, 'kat': {k: True for k in KATEGORILER},
              'sahte': {'konum': 'Lizbon', 'ad': 'Alex', 'bilgisayar': 'DESKTOP-7K2M9X'}}
# Türkçe sözcüklerle karışmayan, kısa, uluslararası takma adlar
TAKMA_HAVUZ = ('Jamie', 'Robin', 'Taylor', 'Morgan', 'Jordan', 'Casey', 'Riley', 'Avery', 'Quinn', 'Dana', 'Skyler', 'Rowan',
               'Elliot', 'Harper', 'Sasha', 'Logan')
AD_ANAHTARLARI = {'name', 'isim', 'ad', 'adi', 'adı', 'user_name', 'username', 'kullanici_adi', 'kullanıcı_adı', 'full_name',
                  'first_name', 'last_name', 'surname', 'soyad', 'soyadi', 'nickname', 'takma_ad', 'kullanici', 'user'}
NUMARA_RE = re.compile(r'(?<![\w.])(?:\+?\d[\d\s\-().]{8,}\d|(?:\+?90|0)?5\d{9})(?![\w])')
YIL_RE = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')

_L = threading.RLock()
_C = {'kural': None, 'kural_t': 0.0, 'gercek_yer': set(), 'tohum': False, 'fikir': {'v': 1, 'savedAt': 0, 'items': {}},
      'kancalar': False, 'harita': None}
KURAL_OMRU = 20.0


def _ek():
    from . import ek
    return ek


# --------------------------------------------------------------------------- ayar
def ayar() -> dict:
    try:
        s = _ek().ayar('yayin', None)
    except Exception:
        s = None
    out = {'acik': False, 'kat': dict(VARSAYILAN['kat']), 'sahte': dict(VARSAYILAN['sahte'])}
    if isinstance(s, dict):
        out['acik'] = bool(s.get('acik'))
        if isinstance(s.get('kat'), dict):
            for k in KATEGORILER:
                if k in s['kat']:
                    out['kat'][k] = bool(s['kat'][k])
        if isinstance(s.get('sahte'), dict):
            for k in out['sahte']:
                v = str(s['sahte'].get(k) or '').strip()
                if v:
                    out['sahte'][k] = v[:60]
        if isinstance(s.get('spot'), dict):
            out['spot'] = s['spot']
    return out


def _yaz(s: dict) -> None:
    store = {'acik': bool(s['acik']), 'kat': s['kat'], 'sahte': s['sahte']}
    if isinstance(s.get('spot'), dict):
        store['spot'] = s['spot']
    _ek().ayar_yaz('yayin', store)
    _C['kural'] = None


def acik() -> bool:
    return bool(ayar()['acik'])


def kat(ad: str) -> bool:
    s = ayar()
    return bool(s['acik'] and s['kat'].get(ad, False))


# --------------------------------------------------------------------------- yer
def sahte_spot() -> dict:
    """geo.chosen() biçiminde sahte konum."""
    s = ayar()
    ad = s['sahte']['konum']
    spot = s.get('spot')
    if isinstance(spot, dict) and spot.get('for') == ad and spot.get('lat') is not None:
        return dict(spot)
    hazir = YER_HAZIR.get(ad) or next((v for k, v in YER_HAZIR.items() if k.casefold() == ad.casefold()), None)
    if hazir:
        return dict(hazir, **{'for': ad})
    h = YER_HAZIR['Lizbon']
    return dict(h, **{'for': h['label']})


def sahte_konum_blogu() -> str:
    """ek.konum_blogu yerine: model gerçek konumu hiç görmez."""
    if not (kat('konum') or kat('hava')):
        return ''
    sp = sahte_spot()
    return (f"[KONUM]\nKullanıcının konumu: {sp['label']} (enlem {sp['lat']}, boylam {sp['lon']}). \"Neredeyim / yakınımda\" "
            'sorularında yalnızca bunu kullan; başka bir yer uydurma ya da tahmin etme.')


def _geo_sar() -> None:
    from . import geo
    if getattr(geo.chosen, '_yayin', False):
        return
    asil = geo.chosen

    def chosen():
        gercek = None
        try:
            gercek = asil()
        except Exception:
            pass
        if gercek and gercek.get('label'):
            _C['gercek_yer'].add(str(gercek['label']))
        if kat('konum') or kat('hava'):
            return sahte_spot()
        return gercek
    chosen._yayin = True
    chosen._asil = asil
    geo.chosen = chosen


# --------------------------------------------------------------------------- gerçek değerler
def _hafiza_ogeleri() -> tuple[list[str], list[str]]:
    """(kişi adları, kimlik adları) — hafızadan; hafıza dosyasına ASLA yazılmaz."""
    kisiler, adlar = [], []
    try:
        from . import memory
        mem = memory.load_memory()
    except Exception:
        return kisiler, adlar
    for cat, items in (mem or {}).items():
        if not isinstance(items, dict):
            continue
        if cat == 'whatsapp_contacts':
            for key, val in items.items():
                kisiler.append(str(key))
                if isinstance(val, dict):
                    if val.get('display_name'):
                        kisiler.append(str(val['display_name']))
                    al = val.get('aliases') or []
                    kisiler.extend(str(a) for a in (al if isinstance(al, list) else [al]) if a)
            continue
        for key, val in items.items():
            if str(key).strip().casefold() in AD_ANAHTARLARI:
                v = val.get('value', val) if isinstance(val, dict) else val
                if isinstance(v, str) and 2 < len(v.strip()) < 60:
                    adlar.append(v.strip())
    try:
        from . import paths
        import json
        pb = getattr(paths, 'PHONEBOOK_FILE', None)
        if pb is not None and pb.exists():
            d = json.loads(pb.read_text(encoding='utf-8'))
            if isinstance(d, dict):
                kisiler.extend(str(k) for k in d)
    except Exception:
        pass
    return kisiler, adlar


def _takma_atamasi(gercekler: list[str], yasak: set[str]) -> dict[str, str]:
    """Kişi → sabit takma ad (ayarda saklanır; kişi kümesi değişse de eskiler aynı kalır)."""
    try:
        kayit = _ek().ayar('yayin_takma', None)
    except Exception:
        kayit = None
    kayit = dict(kayit) if isinstance(kayit, dict) else {}
    kullanilan = {v.casefold() for v in kayit.values()} | {y.casefold() for y in yasak}
    degisti = False
    for g in sorted({x.strip() for x in gercekler if len(x.strip()) >= 3}, key=lambda x: x.casefold()):
        anahtar = g.casefold()
        if anahtar in kayit:
            continue
        i = int(hashlib.sha1(anahtar.encode('utf-8')).hexdigest()[:8], 16) % len(TAKMA_HAVUZ)
        for sira in range(len(TAKMA_HAVUZ) * 4):
            ad = TAKMA_HAVUZ[(i + sira) % len(TAKMA_HAVUZ)]
            if sira >= len(TAKMA_HAVUZ):
                ad = f'{ad} {sira // len(TAKMA_HAVUZ) + 1}'
            if ad.casefold() not in kullanilan:
                kayit[anahtar] = ad
                kullanilan.add(ad.casefold())
                degisti = True
                break
    if degisti:
        try:
            _ek().ayar_yaz('yayin_takma', kayit)
        except Exception:
            pass
    return kayit


def _kimlik_gercek() -> dict[str, list[str]]:
    """{'kullanici': [...], 'bilgisayar': [...]} — işletim sisteminden."""
    kul, bil = [], []
    for fn in (getpass.getuser,):
        try:
            kul.append(fn())
        except Exception:
            pass
    for e in ('USERNAME', 'USER', 'LOGNAME'):
        if os.environ.get(e):
            kul.append(os.environ[e])
    for fn in (socket.gethostname,):
        try:
            bil.append(fn())
        except Exception:
            pass
    for e in ('COMPUTERNAME', 'HOSTNAME'):
        if os.environ.get(e):
            bil.append(os.environ[e])
    ok = lambda xs: [x for x in dict.fromkeys(x.strip() for x in xs) if len(x) >= 3 and x.casefold() not in ('root', 'user', 'admin', 'localhost')]  # noqa: E731
    return {'kullanici': ok(kul), 'bilgisayar': ok(bil)}


def _kural() -> dict:
    """Aktif değiştirme kuralları (kısa süre önbellekli): {'ileri': [(gerçek, sahte, tam_sozcuk)], 'geri': {sahte_lower: gerçek}}."""
    with _L:
        if _C['kural'] is not None and time.time() - _C['kural_t'] < KURAL_OMRU:
            return _C['kural']
        s = ayar()
        ileri, geri = [], {}
        if s['acik']:
            kisiler, adlar = _hafiza_ogeleri()
            if s['kat']['kimlik']:
                sa, sb = s['sahte']['ad'], s['sahte']['bilgisayar']
                kimlik = _kimlik_gercek()
                for g in adlar + kimlik['kullanici']:
                    ileri.append((g, sa, True)); geri.setdefault(sa.casefold(), g)
                for g in kimlik['bilgisayar']:
                    ileri.append((g, sb, True)); geri.setdefault(sb.casefold(), g)
            if s['kat']['kisiler']:
                yasak = {s['sahte']['ad']} | {x[1] for x in ileri}
                tablo = _takma_atamasi(kisiler, yasak)
                for g in sorted(set(kisiler), key=len, reverse=True):
                    t = tablo.get(g.strip().casefold())
                    if t and len(g.strip()) >= 3:
                        ileri.append((g.strip(), t, False)); geri.setdefault(t.casefold(), g.strip())
            if s['kat']['konum'] or s['kat']['hava']:
                sahte = sahte_spot()['label']
                gercek = set(_C['gercek_yer'])
                try:
                    from . import settings
                    txt = str(settings.get('location') or '').strip()
                    if txt:
                        gercek.add(txt)
                    sp = settings.get('location_spot')
                    if isinstance(sp, dict) and sp.get('label'):
                        gercek.add(str(sp['label']))
                except Exception:
                    pass
                for g in gercek:
                    for parca in {g, g.split(',')[0].strip()}:
                        if len(parca) >= 3 and parca.casefold() != sahte.casefold():
                            ileri.append((parca, sahte, False))          # konum geri çevrilmez: araçlar sahte yerle çalışır
        ileri.sort(key=lambda x: len(x[0]), reverse=True)
        derlenmis = None
        if ileri:
            parcalar = []
            for g, _, tam in ileri:
                p = re.escape(g)
                parcalar.append(p + (r'(?![\wçğıöşüÇĞİÖŞÜ])' if tam else r'(?![a-zçğıöşü]{5,})'))
            derlenmis = re.compile(r'(?<![\wçğıöşüÇĞİÖŞÜ])(?:' + '|'.join(parcalar) + ')', re.IGNORECASE)
        harita = {}
        for g, sa, _ in ileri:
            harita.setdefault(_kucuk(g), sa)
        geri_re = None
        if geri:
            geri_re = re.compile(r'(?<![\wçğıöşüÇĞİÖŞÜ])(?:' + '|'.join(re.escape(k) for k in sorted(geri, key=len, reverse=True)) + r')(?![\wçğıöşüÇĞİÖŞÜ])', re.IGNORECASE)
        _C['kural'] = {'acik': s['acik'], 're': derlenmis, 'harita': harita, 'geri': geri, 'geri_re': geri_re, 'numara': bool(s['acik'] and s['kat']['kisiler']),
                       'ileri_sayi': len(ileri)}
        _C['kural_t'] = time.time()
        return _C['kural']


def _kucuk(t: str) -> str:
    return t.replace('İ', 'i').replace('I', 'ı').lower().replace('i̇', 'i')


def _uyarla(eslesen: str, sahte: str) -> str:
    if eslesen.isupper() and len(eslesen) > 1:
        return sahte.upper()
    return sahte


def _numara_maske(m: re.Match) -> str:
    t = m.group(0)
    sayi = sum(c.isdigit() for c in t)
    if sayi < 10 or YIL_RE.search(t):                  # tarih/saat gibi görünenlere dokunma
        return t
    if sayi == len(t.lstrip('+')) and not re.fullmatch(r'(?:\+?90|0)?5\d{9}', t):
        return t                                       # ayraçsız uzun sayı (kimlik/zaman damgası): telefon deseni değilse dokunma
    return '••• ••• •• ••'


# --------------------------------------------------------------------------- metin değiştirme
def maskele_metin(t: str) -> str:
    if not isinstance(t, str) or not t:
        return t
    k = _kural()
    if not k['acik']:
        return t
    if k['re'] is not None:
        t = k['re'].sub(lambda m: _uyarla(m.group(0), k['harita'].get(_kucuk(m.group(0)))
                                          or next((v for g, v in k['harita'].items() if _kucuk(m.group(0)).startswith(g)), 'Alex')), t)
    if k['numara']:
        t = NUMARA_RE.sub(_numara_maske, t)
    return t


def maskele(o, derin: int = 0):
    """Metin/liste/sözlük içindeki dizgelerde (sözlük anahtarları dahil) gerçek değerleri sahteyle değiştirir."""
    if not acik() or derin > 12:
        return o
    if isinstance(o, str):
        return maskele_metin(o)
    if isinstance(o, list):
        return [maskele(x, derin + 1) for x in o]
    if isinstance(o, tuple):
        return tuple(maskele(x, derin + 1) for x in o)
    if isinstance(o, dict):
        return {(maskele_metin(k) if isinstance(k, str) else k): maskele(v, derin + 1) for k, v in o.items()}
    return o


def gercege_cevir_metin(t: str) -> str:
    if not isinstance(t, str) or not t:
        return t
    k = _kural()
    if not k['acik'] or k['geri_re'] is None:
        return t
    return k['geri_re'].sub(lambda m: k['geri'].get(m.group(0).casefold(), m.group(0)), t)


def gercege_cevir(o, derin: int = 0):
    """Modelin araç argümanlarındaki takma ad/sahte ad → gerçek (konum geri çevrilmez)."""
    if derin > 12 or not acik():
        return o
    if isinstance(o, str):
        return gercege_cevir_metin(o)
    if isinstance(o, list):
        return [gercege_cevir(x, derin + 1) for x in o]
    if isinstance(o, dict):
        return {k: gercege_cevir(v, derin + 1) for k, v in o.items()}
    return o


# --------------------------------------------------------------------------- Fikir (demo veri)
def fikir_oku() -> dict:
    with _L:
        return {'v': 1, 'savedAt': _C['fikir'].get('savedAt', 0), 'items': dict(_C['fikir']['items'])}


def fikir_yaz(snap: dict) -> None:
    with _L:
        _C['fikir'] = {'v': 1, 'savedAt': int(time.time() * 1000), 'items': dict((snap or {}).get('items', {}))}


DEMO_GOREVLER = ('Haftalık rapor taslağını hazırla', 'Spor salonu: 45 dk', 'Market listesini tamamla', 'Kitap: 30 sayfa oku')
DEMO_FIKIRLER = (('Yayın için küçük bir overlay', 'Yayında sohbet ve saat gösteren sade bir katman.'),
                 ('Bahçe sulama zamanlayıcısı', 'Toprak nemine göre çalışan basit bir devre.'))


def _fikir_tohumla() -> None:
    """Demo verisini gerçek işlevlerle yazar (şema doğru olsun); yazılan yer bellektir, disk değil."""
    from . import ek_fikir as F
    with _L:
        _C['fikir'] = {'v': 1, 'savedAt': 0, 'items': {}}
    try:
        for g in DEMO_GOREVLER:
            F.gorev_ekle(g)
        for b, m in DEMO_FIKIRLER:
            F.fikir_ekle(m, b)
        F.not_yaz('Toplantı notları (demo)', 'Bu yalnızca yayın modunda görünen örnek bir nottur.')
    except Exception as exc:
        log('ek_yayin: demo veri yazılamadı', type(exc).__name__, exc)


# --------------------------------------------------------------------------- kancalar
def kur(a=None) -> None:
    """Sarmalayıcıları bir kez kurar (HUD çıkışı, araç çağrısı, hafıza istemi, konum kaynağı)."""
    with _L:
        if _C['kancalar']:
            return
        _C['kancalar'] = True
    try:
        from .ui import window as W
        asil_call = W.Hud.call

        def call(self, method, *args):
            if method != 'level' and acik():
                try:
                    args = tuple(maskele(x) for x in args)
                except Exception as exc:
                    log('ek_yayin: maskeleme hatası, çağrı atlandı', type(exc).__name__)
                    return None
            return asil_call(self, method, *args)
        call._yayin = True
        W.Hud.call = call
    except Exception as exc:
        log('ek_yayin: HUD kancası kurulamadı', type(exc).__name__)
    try:
        import importlib
        R = importlib.import_module('.tools.registry', __package__)     # (tools.registry paket özniteliği bir örnek: modülü doğrudan al)
        asil_ara = R.Registry.call

        def cagir(self, name, args, ctx):
            if not acik() or name == 'yayin':
                return asil_ara(self, name, args, ctx)
            if name in ('save_memory', 'delete_memory') and kat('hafiza'):
                return 'Yayın modunda hafıza kapalı: kaydedilmedi/silinmedi.', True
            try:
                args = gercege_cevir(args)
            except Exception:
                pass
            metin, ok = asil_ara(self, name, args, ctx)
            try:
                return maskele(metin), ok
            except Exception:
                return 'Sonuç yayın modu nedeniyle gösterilemedi.', ok
        R.Registry.call = cagir
    except Exception as exc:
        log('ek_yayin: araç kancası kurulamadı', type(exc).__name__)
    try:
        from . import memory
        asil_fmt = memory.format_memory_for_prompt

        def format_memory_for_prompt(mem):
            if kat('hafiza'):
                return ''
            out = asil_fmt(mem)
            return maskele(out) if acik() else out
        memory.format_memory_for_prompt = format_memory_for_prompt
    except Exception as exc:
        log('ek_yayin: hafıza kancası kurulamadı', type(exc).__name__)
    try:
        from . import app as A
        asil_duz = A.App._flat_memory

        def _flat_memory():
            return {} if kat('hafiza') else asil_duz()
        A.App._flat_memory = staticmethod(_flat_memory)
    except Exception as exc:
        log('ek_yayin: hafıza paneli kancası kurulamadı', type(exc).__name__)
    try:
        _geo_sar()
    except Exception as exc:
        log('ek_yayin: konum kancası kurulamadı', type(exc).__name__)


def istem() -> str:
    s = ayar()
    if not s['acik']:
        return ''
    k = s['kat']
    satirlar = ['[YAYIN MODU AÇIK] Kullanıcı canlı yayında/ekran paylaşıyor. Gerçek kişisel bilgiyi ASLA söyleme, yazma ya da tahmin etme.']
    if k['kimlik']:
        satirlar.append(f"Kullanıcının adı yayında \"{s['sahte']['ad']}\"; bilgisayarın adı \"{s['sahte']['bilgisayar']}\". Gerçek adı sorarsa \"yayındayım, bunu söylemeyeyim\" de.")
    if k['kisiler']:
        satirlar.append('Rehberdeki kişileri yalnızca araç sonuçlarında gördüğün takma adlarla an; numara söyleme. Kullanıcı gerçek ad söylese bile cevabında takma adı kullan.')
    if k['konum'] or k['hava']:
        satirlar.append(f"Konum bilgisi (kullanıcı yayında): {sahte_spot()['label']}. Başka bir yer söyleme.")
    if k['hafiza']:
        satirlar.append('Kişisel hafıza bu yayında kapalı: kullanıcı hakkında önceden bildiğin kişisel bir şey varmış gibi davranma.')
    if k['fikir']:
        satirlar.append('Fikir Alanım bu yayında DEMO verisiyle çalışıyor (gerçek verilere dokunulmuyor).')
    return '\n'.join(satirlar)


# --------------------------------------------------------------------------- kontrol
def _spot_coz(yer: str) -> tuple[dict | None, str]:
    for k, v in YER_HAZIR.items():
        if k.casefold() == yer.casefold():
            return dict(v, **{'for': k}), ''
    try:
        from . import geo
        hit = geo.geocode(yer, details=True)
    except Exception:
        return None, 'Yer aranamadı (internet yok gibi). Hazır listeden seç: ' + ', '.join(YER_HAZIR)
    if not hit:
        return None, f'“{yer}” bulunamadı. Hazır listeden seç: ' + ', '.join(YER_HAZIR)
    try:
        label = geo.short_tr(hit)
        zoom = geo._panel_zoom(hit.get('bbox'))
    except Exception:
        label, zoom = yer, 11
    return {'for': yer, 'label': label, 'lat': round(hit['lat'], 5), 'lon': round(hit['lon'], 5), 'zoom': zoom,
            'country': str((hit.get('addr') or {}).get('country') or '')}, ''


def ayarla(acik_: bool | None = None, kategori: dict | None = None, konum: str | None = None, ad: str | None = None,
           bilgisayar: str | None = None) -> str:
    """Tek giriş: mod aç/kapat, kategori aç/kapat, sahte değerler. Döner: kullanıcıya/modele kısa durum metni."""
    from . import ek_fikir as F
    hata = ''
    s = ayar()
    eski_fikir = bool(s['acik'] and s['kat']['fikir'])
    eski_acik = s['acik']
    if konum:
        sp, h = _spot_coz(' '.join(konum.split())[:60])          # ağ gerekebilir: kilit tutulmaz
        if sp:
            s['sahte']['konum'] = sp['for']; s['spot'] = sp
        else:
            hata = h
    if ad and len(ad.strip()) >= 2:
        s['sahte']['ad'] = ad.strip()[:40]
    if bilgisayar and len(bilgisayar.strip()) >= 3:
        s['sahte']['bilgisayar'] = bilgisayar.strip()[:40]
    if isinstance(kategori, dict):
        for k, v in kategori.items():
            if k in KATEGORILER:
                s['kat'][k] = bool(v)
    if acik_ is not None:
        s['acik'] = bool(acik_)
    yeni_fikir = bool(s['acik'] and s['kat']['fikir'])
    kayit, ep_eski = {}, 0
    if yeni_fikir != eski_fikir:
        # Fikir kaynağı değişiyor: sayfanın son bildiği hâl (3'lü birleştirme tabanı) ESKİ kaynaktan alınır, sürüm artırılır.
        with F._L:
            try:
                taban = dict(F.snapshot_oku()['items'])           # bayrak henüz eski: eski kaynak
            except Exception:
                taban = {}
            ep_eski = F._F['epoch']
            F._F['onceki'][ep_eski] = taban
            kayit = dict(F._F['onceki'])
    with _L:
        _yaz(s)
    if yeni_fikir != eski_fikir:
        if yeni_fikir:
            _fikir_tohumla()
        with F._L:
            F._F['onceki'].clear()
            F._F['onceki'].update(kayit)                           # tohumlama geçmişi itmesin
            F._F['epoch'] = max(F._F['epoch'], ep_eski) + 1        # bayat sayfa doğrudan yazamaz; birleştirmeye girer
    _yenile_arka(s['acik'] or eski_acik)
    return durum_metni() + (f' Uyarı: {hata}' if hata else '')


def _yenile_arka(oturum: bool) -> None:
    threading.Thread(target=_yenile, args=(oturum,), daemon=True).start()


def _yenile(oturum: bool) -> None:
    """Ekranı yenile; asistan oturumunu yeni talimatla yeniden kur."""
    try:
        e = _ek()
        a = getattr(e, 'app', None)
        if a is None:
            return
        try:
            from . import panels
            a.hud.call('panel', panels.weather(force=True))
        except Exception:
            pass
        try:
            e._hud('ekDurum', e.durum())
            e._hud('ekFikirYenile')
        except Exception:
            pass
        if oturum:
            try:
                a.brain.reconnect()
            except Exception as exc:
                log('ek_yayin: oturum yenilenemedi', type(exc).__name__)
    except Exception as exc:
        log('ek_yayin: yenileme hatası', type(exc).__name__)


def durum() -> dict:
    s = ayar()
    return {'acik': s['acik'], 'kat': s['kat'], 'sahte': s['sahte'], 'etiket': ETIKET, 'yerler': list(YER_HAZIR)}


def durum_metni() -> str:
    s = ayar()
    if not s['acik']:
        return 'Yayın modu kapalı.'
    acik_kat = [ETIKET[k] for k in KATEGORILER if s['kat'][k]]
    return (f"Yayın modu AÇIK. Sahte konum: {s['sahte']['konum']}, ad: {s['sahte']['ad']}, bilgisayar: {s['sahte']['bilgisayar']}. "
            f"Gizlenenler: {', '.join(acik_kat) or 'hiçbiri'}.")


def arac(a: dict | None, _c=None) -> str:
    a = a or {}
    e = str(a.get('eylem') or 'durum')
    if e == 'durum':
        return durum_metni()
    if e == 'ac':
        return ayarla(acik_=True)
    if e == 'kapat':
        return ayarla(acik_=False)
    if e == 'ayarla':
        kat_ = {}
        for k in KATEGORILER:
            if a.get(k) is not None:
                kat_[k] = bool(a[k])
        return ayarla(kategori=kat_ or None, konum=a.get('konum'), ad=a.get('ad'), bilgisayar=a.get('bilgisayar'))
    return 'Hata: bilinmeyen eylem. durum | ac | kapat | ayarla.'
