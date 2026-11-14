"""BLOOM EK — Mark 2 ana ekranının panosu: hava (Open-Meteo), döviz (TCMB), haber başlıkları (RSS).

jarvis-main (halilozat/jarvis, MIT) sunucusundaki dashboard.ts/news.ts'in Python karşılığı. Kural aynı: UYDURMA VERİ YOK; bir kaynak
çökerse yalnızca o alan boş (None / eksik) gelir, ekran "alınamadı" der. Hepsi anahtarsızdır; ağ yalnızca burada kullanılır.
Yayın modunda konum sahte konumdur (ek_yayin) ve gerçek koordinat hiç sorulmaz.
"""
from __future__ import annotations
import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from .log import log

ZAMAN_ASIMI = 8.0
UA = 'Mozilla/5.0 (BLOOM)'

WMO = {
    0: ('Açık', 'acik'), 1: ('Çoğunlukla açık', 'parcali'), 2: ('Parçalı bulutlu', 'parcali'), 3: ('Bulutlu', 'bulutlu'),
    45: ('Sisli', 'sis'), 48: ('Kırağılı sis', 'sis'), 51: ('Hafif çisenti', 'cisenti'), 53: ('Çisenti', 'cisenti'),
    55: ('Yoğun çisenti', 'cisenti'), 56: ('Dondurucu çisenti', 'cisenti'), 57: ('Yoğun dondurucu çisenti', 'cisenti'),
    61: ('Hafif yağmur', 'yagmur'), 63: ('Yağmurlu', 'yagmur'), 65: ('Şiddetli yağmur', 'yagmur'),
    66: ('Dondurucu yağmur', 'yagmur'), 67: ('Şiddetli dondurucu yağmur', 'yagmur'),
    71: ('Hafif kar', 'kar'), 73: ('Karlı', 'kar'), 75: ('Yoğun kar', 'kar'), 77: ('Kar taneleri', 'kar'),
    80: ('Hafif sağanak', 'saganak'), 81: ('Sağanak', 'saganak'), 82: ('Şiddetli sağanak', 'saganak'),
    85: ('Kar sağanağı', 'kar'), 86: ('Yoğun kar sağanağı', 'kar'),
    95: ('Gök gürültülü fırtına', 'firtina'), 96: ('Dolulu fırtına', 'firtina'), 99: ('Şiddetli dolulu fırtına', 'firtina'),
}

# (ad, adres, kategori)
HABER_KAYNAKLARI = [
    ('TRT Haber', 'https://www.trthaber.com/gundem_articles.rss', 'gundem'),
    ('TRT Haber', 'https://www.trthaber.com/ekonomi_articles.rss', 'ekonomi'),
    ('TRT Haber', 'https://www.trthaber.com/dunya_articles.rss', 'dunya'),
    ('TRT Haber', 'https://www.trthaber.com/bilim_teknoloji_articles.rss', 'teknoloji'),
    ('TRT Haber', 'https://www.trthaber.com/spor_articles.rss', 'spor'),
    ('BBC Türkçe', 'https://feeds.bbci.co.uk/turkce/rss.xml', 'dunya'),
]

_L = threading.RLock()
_ONBELLEK: dict[str, dict] = {}


def _al(url: str, sure: float = ZAMAN_ASIMI) -> bytes:
    r = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(r, timeout=sure) as f:
        return f.read(3_000_000)


def _onbellekli(anahtar: str, ok_sn: float, hata_sn: float, yukle):
    """Başarıyı ok_sn, başarısızlığı hata_sn tutar (kaynak çökükken her istekte yeniden denenmez)."""
    with _L:
        e = _ONBELLEK.get(anahtar)
        if e and time.time() - e['t'] < (ok_sn if e['v'] is not None else hata_sn):
            return e['v']
    try:
        v = yukle()
    except Exception as exc:
        log('ek_pano:', anahtar, 'alınamadı', type(exc).__name__, str(exc)[:80])
        v = None
    with _L:
        eski = _ONBELLEK.get(anahtar)
        # başarısızsa eski (bayat ama gerçek) veriyi 1 saate kadar göster
        if v is None and eski and eski['v'] is not None and time.time() - eski['t'] < 3600:
            _ONBELLEK[anahtar] = {'t': time.time() - ok_sn + hata_sn, 'v': eski['v']}
            return eski['v']
        _ONBELLEK[anahtar] = {'t': time.time(), 'v': v}
    return v


def _say(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and v == v else None


# --------------------------------------------------------------------------- konum
def konum() -> dict | None:
    """{ad, lat, lon}. Yayın modunda sahte konum; yoksa BLOOM'un hava paneli/seçili konumu. Bulunamazsa None."""
    try:
        from . import ek_yayin
        if ek_yayin.kat('konum') or ek_yayin.kat('hava'):
            s = ek_yayin.sahte_spot()
            return {'ad': str(s.get('label') or ''), 'lat': float(s['lat']), 'lon': float(s['lon'])}
    except Exception:
        pass
    try:
        from . import geo
        s = geo.chosen()
        if s and s.get('lat') is not None:
            return {'ad': str(s.get('label') or ''), 'lat': float(s['lat']), 'lon': float(s['lon'])}
    except Exception:
        pass
    try:
        from . import panels
        w = panels.weather()
        if w and w.get('lat') is not None and w.get('lon') is not None:
            return {'ad': str(w.get('place') or ''), 'lat': float(w['lat']), 'lon': float(w['lon'])}
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- hava
def _hava_yukle(k: dict) -> dict:
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={k['lat']:.3f}&longitude={k['lon']:.3f}"
           '&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m'
           '&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset'
           '&hourly=temperature_2m,precipitation_probability&timezone=auto&forecast_days=2')
    j = json.loads(_al(url).decode('utf-8'))
    c, d, h = j.get('current') or {}, j.get('daily') or {}, j.get('hourly') or {}
    temp, feels, code, wind = (_say(c.get('temperature_2m')), _say(c.get('apparent_temperature')),
                               _say(c.get('weather_code')), _say(c.get('wind_speed_10m')))
    mx = _say((d.get('temperature_2m_max') or [None])[0])
    mn = _say((d.get('temperature_2m_min') or [None])[0])
    dkod = _say((d.get('weather_code') or [None])[0])
    if None in (temp, feels, code, wind, mx, mn, dkod):
        raise ValueError('Open-Meteo cevabında eksik alan')       # eksik alanı tahminle doldurmuyoruz
    aciklama, ikon = WMO.get(int(code), ('Bilinmiyor', 'bulutlu'))
    zamanlar = h.get('time') or []
    simdi = str(c.get('time') or '')[:13]
    bas = next((i for i, t in enumerate(zamanlar) if str(t)[:13] == simdi), 0)
    saatlik = []
    for i in range(bas, len(zamanlar)):
        if len(saatlik) >= 12:
            break
        t = _say((h.get('temperature_2m') or [None] * (i + 1))[i])
        if t is None:
            continue
        saatlik.append({'time': str(zamanlar[i])[11:16], 'temp': t, 'rain_prob': _say((h.get('precipitation_probability') or [None] * (i + 1))[i])})
    gd = (d.get('sunrise') or [None])[0]
    gb = (d.get('sunset') or [None])[0]
    return {'city': k['ad'] or 'Konum', 'lat': k['lat'], 'lon': k['lon'], 'temp': temp, 'feels_like': feels, 'code': int(code),
            'description': aciklama, 'icon': ikon, 'wind': wind,
            'today': {'max': mx, 'min': mn, 'rain_prob': _say((d.get('precipitation_probability_max') or [None])[0]), 'code': int(dkod)},
            'hourly': saatlik, 'sunrise': str(gd)[11:16] if gd else None, 'sunset': str(gb)[11:16] if gb else None,
            'updated_at': str(c.get('time') or dt.datetime.now().isoformat(timespec='minutes'))}


def hava() -> dict | None:
    k = konum()
    if not k:
        return None
    anahtar = f"hava:{k['lat']:.2f},{k['lon']:.2f}:{k['ad']}"
    return _onbellekli(anahtar, 600, 60, lambda: _hava_yukle(k))


# --------------------------------------------------------------------------- döviz (TCMB)
KODLAR = ('USD', 'EUR', 'GBP')
ADLAR = {'USD': 'ABD Doları', 'EUR': 'Euro', 'GBP': 'İngiliz Sterlini'}


def tcmb_coz(xml: str) -> tuple[str, dict[str, float]] | None:
    t = re.search(r'<Tarih_Date[^>]*\bTarih="(\d{2})\.(\d{2})\.(\d{4})"', xml)
    if not t:
        return None
    oranlar: dict[str, float] = {}
    for kod in KODLAR:
        b = re.search(r'<Currency[^>]*\bKod="' + kod + r'"[^>]*>([\s\S]*?)</Currency>', xml)
        v = b and re.search(r'<ForexSelling>\s*([\d.]+)\s*</ForexSelling>', b.group(1))
        if v:
            oranlar[kod] = float(v.group(1))
    return f'{t.group(3)}-{t.group(2)}-{t.group(1)}', oranlar


def _tcmb_gun(gun: dt.date | None) -> tuple[str, dict[str, float]] | None:
    url = ('https://www.tcmb.gov.tr/kurlar/today.xml' if gun is None
           else f'https://www.tcmb.gov.tr/kurlar/{gun:%Y%m}/{gun:%d%m%Y}.xml')
    try:
        return tcmb_coz(_al(url).decode('utf-8', 'replace'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None                  # hafta sonu / resmi tatil: bülten yok
        raise


def _doviz_yukle() -> dict:
    bugun = _tcmb_gun(None)
    if not bugun:
        raise ValueError('TCMB bülteni okunamadı')
    gunler, gun = [], dt.date.today()
    while len(gunler) < 7:                       # son 7 iş günü adayı (tatiller 404 verir, atlanır)
        gun -= dt.timedelta(days=1)
        if gun.weekday() < 5:
            gunler.append(gun)
    bulten: dict[dt.date, tuple[str, dict[str, float]] | None] = {}

    def getir(g: dt.date) -> None:
        try:
            bulten[g] = _tcmb_gun(g)
        except Exception:
            bulten[g] = None

    ts = [threading.Thread(target=getir, args=(g,), daemon=True) for g in gunler]
    for t in ts:
        t.start()
    for t in ts:
        t.join(ZAMAN_ASIMI + 2)
    gecmis = [b for g in sorted(gunler, reverse=True) for b in [bulten.get(g)] if b and b[0] != bugun[0]][:5]
    gecmis.reverse()
    seri = gecmis + [bugun]
    ogeler = []
    for kod in KODLAR:
        if kod not in bugun[1]:
            continue
        gec = [{'date': d, 'value': r[kod]} for d, r in seri if kod in r]
        onceki = next((r[kod] for d, r in reversed(gecmis) if kod in r), None)
        degisim = round((bugun[1][kod] - onceki) / onceki * 100, 2) if onceki else None
        ogeler.append({'code': kod, 'name': ADLAR[kod], 'value': bugun[1][kod], 'change_pct': degisim, 'history': gec})
    if not ogeler:
        raise ValueError('TCMB bülteninde kur yok')
    return {'items': ogeler, 'date': bugun[0], 'source': 'TCMB'}


def doviz() -> dict | None:
    return _onbellekli('doviz', 3600, 120, _doviz_yukle)


# --------------------------------------------------------------------------- haber (RSS)
def _etiket(e: ET.Element, ad: str) -> str:
    for c in e:
        if c.tag.split('}')[-1] == ad and c.text:
            return c.text.strip()
    return ''


def rss_coz(xml: bytes, kaynak: str, kategori: str) -> list[dict]:
    kok = ET.fromstring(xml)
    out = []
    for it in kok.iter('item'):
        baslik = re.sub(r'\s+', ' ', _etiket(it, 'title')).strip()
        if not baslik:
            continue
        try:
            zaman = parsedate_to_datetime(_etiket(it, 'pubDate')).astimezone(dt.timezone.utc).isoformat()
        except Exception:
            zaman = dt.datetime.now(dt.timezone.utc).isoformat()
        out.append({'title': baslik, 'source': kaynak, 'category': kategori, 'image': None, 'published_at': zaman})
    return out


def _haber_yukle() -> dict:
    sonuc: list[tuple[str, str, list[dict] | None]] = [('', '', None)] * len(HABER_KAYNAKLARI)

    def calis(i: int, ad: str, url: str, kat: str) -> None:
        try:
            sonuc[i] = (ad, kat, rss_coz(_al(url), ad, kat))
        except Exception as exc:
            log('ek_pano: haber kaynağı alınamadı', ad, type(exc).__name__)
            sonuc[i] = (ad, kat, None)

    ts = [threading.Thread(target=calis, args=(i, *k), daemon=True) for i, k in enumerate(HABER_KAYNAKLARI)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(ZAMAN_ASIMI + 4)
    hepsi: list[dict] = []
    kaynaklar: dict[str, dict] = {}
    for ad, kat, liste in sonuc:
        ok = liste is not None
        k = kaynaklar.setdefault(ad or '?', {'name': ad or '?', 'ok': False, 'count': 0})
        if ok:
            k['ok'] = True
            k['count'] += len(liste or [])
            hepsi.extend(liste or [])
    # aynı başlık iki kez gelmesin
    goruldu, tekil = set(), []
    for h in sorted(hepsi, key=lambda x: x['published_at'], reverse=True):
        a = h['title'].casefold()
        if a in goruldu:
            continue
        goruldu.add(a)
        tekil.append(h)
    kat_say: dict[str, int] = {}
    for h in tekil:
        kat_say[h['category']] = kat_say.get(h['category'], 0) + 1
    # kategori dengesi: manşet listesi tek kategoriden dolmasın
    secili, sayac = [], {}
    for h in tekil:
        if sayac.get(h['category'], 0) >= 3:
            continue
        sayac[h['category']] = sayac.get(h['category'], 0) + 1
        secili.append(h)
        if len(secili) >= 14:
            break
    ok_say = sum(1 for k in kaynaklar.values() if k['ok'])
    if not tekil:
        raise ValueError('hiçbir haber kaynağına ulaşılamadı')
    return {'total': len(tekil), 'sources_ok': ok_say, 'sources_total': len(kaynaklar),
            'by_category': [{'category': c, 'count': n} for c, n in sorted(kat_say.items(), key=lambda x: -x[1])],
            'headlines': secili, 'sources': list(kaynaklar.values())}


def haber() -> dict | None:
    return _onbellekli('haber', 600, 90, _haber_yukle)


# --------------------------------------------------------------------------- pano
BOS_HABER = {'total': 0, 'sources_ok': 0, 'sources_total': len(set(k[0] for k in HABER_KAYNAKLARI)), 'by_category': [],
             'headlines': [], 'sources': []}


def pano() -> dict:
    sonuc: dict[str, object] = {}

    def al(ad, f):
        try:
            sonuc[ad] = f()
        except Exception as exc:
            log('ek_pano:', ad, type(exc).__name__)
            sonuc[ad] = None

    ts = [threading.Thread(target=al, args=(a, f), daemon=True) for a, f in (('weather', hava), ('markets', doviz), ('news', haber))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(ZAMAN_ASIMI + 8)
    return {'weather': sonuc.get('weather'), 'markets': sonuc.get('markets'), 'news': sonuc.get('news') or dict(BOS_HABER),
            'system': {'routellm_ms': None, 'routellm_ok': True, 'devices_online': [], 'model': 'gemini-live'},
            'updated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'demo': False}
