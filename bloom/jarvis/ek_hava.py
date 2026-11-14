"""BLOOM EK — hava durumu yalnızca GEREKİNCE yenilenir.

V4 her 5 dakikada bir (önbellek 10 dk) hava durumunu yeniden çekip panele basıyordu. Burada:
  · V4'ün periyodik yenilemesi susturulur (panels iş parçacığının hava çağrısı atlanır; önbellek 12 saat geçerli sayılır).
  · Hava yalnızca şu durumlarda yenilenir:  saat başı değişince  ·  konum değişince  ·  bilgisayar uykudan dönünce
    ·  son deneme başarısız olduysa (bağlantı yoktu; 2 dk'dan başlayıp en çok 15 dk aralıkla yeniden dener).
  · Panel, veri GERÇEKTEN değiştiyse (ya da saat başı güncellemesinde "güncellendi" saati için) HUD'a basılır.
Kontrol döngüsü her 30 sn'de bir yalnızca saate bakar; ağ kullanmaz.
"""

from __future__ import annotations
import datetime as dt
import json
import random
import threading
import time
from .log import log

KONTROL_SN = 30.0
UYKU_ESIGI = 150.0           # duvar saati bu kadar saniye fazla ilerlediyse (monotonik ilerlemediyse) → uykudan dönüldü
HATA_ILK = 120.0
HATA_EN_COK = 900.0
FRESH = 12 * 3600.0

_lock = threading.RLock()
_S = {'t': None, 'kuruldu': False, 'ilk_gecti': False, 'orijinal_one': None, 'saat': None, 'konum': None,
      'hata': 0, 'son_deneme': 0.0, 'duvar': None, 'mono': None, 'itilen': None, 'sebepler': []}


def _simdi() -> dt.datetime:
    return dt.datetime.now()


def _duvar() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


def _acik() -> bool:
    try:
        from . import ek
        return bool(ek.ayar('hava_akilli', True))
    except Exception:
        return True


def _sorgu() -> tuple:
    from . import geo, settings
    spot = geo.chosen()
    location = str(settings.get('location') or '').strip()
    query = geo.coords(spot) if spot else location
    place = spot['label'] if spot else location
    return query, place, spot


def _temiz(d):
    """Karşılaştırma için: 'updated' (güncellenme saati) gibi her yenilemede değişen alanlar atılır."""
    if isinstance(d, dict):
        return {k: _temiz(v) for k, v in d.items() if k != 'updated'}
    if isinstance(d, list):
        return [_temiz(v) for v in d]
    return d


def _imza(d) -> str:
    try:
        return json.dumps(_temiz(d), sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(d)


# --------------------------------------------------------------------------- V4'ün periyodik yenilemesini sustur
def kur() -> bool:
    """panels.WEATHER_FRESH uzatılır; 'panels' iş parçacığının periyodik hava çağrısı atlanır (ilk açılış çağrısı hariç)."""
    from . import panels
    with _lock:
        if _S['kuruldu']:
            return True
        panels.WEATHER_FRESH = FRESH
        orijinal = panels.one
        _S['orijinal_one'] = orijinal

        def one(key):
            if key == 'weather' and threading.current_thread().name == 'panels' and _acik():
                if not _S['ilk_gecti']:
                    _S['ilk_gecti'] = True          # açılışta paneller bir kez dolsun
                else:
                    return None                     # periyodik yenileme: yalnızca ek_hava karar verir
            return orijinal(key)

        one._ek_hava = True
        panels.one = one
        _S['kuruldu'] = True
    return True


# --------------------------------------------------------------------------- karar
def sebep(simdi: dt.datetime, duvar: float, mono: float) -> str | None:
    """Şimdi hava yenilenmeli mi? Neden ('saat' | 'uyku' | 'konum' | 'hata') ya da None. Yan etkisi: duvar/mono kaydı."""
    with _lock:
        eski_d, eski_m = _S['duvar'], _S['mono']
        _S['duvar'], _S['mono'] = duvar, mono
        anahtar = (simdi.date().isoformat(), simdi.hour)
        if _S['saat'] is None:                     # ilk bakış: açılışta çekilen veri bu saat için geçerli
            _S['saat'] = anahtar
            try:
                _S['konum'] = _sorgu()[0]
            except Exception:
                _S['konum'] = None
            try:                                   # açılıştaki çekim başarısızsa (V4 'bağlantı yok' koyar) yeniden dene
                from . import panels
                v = panels._WEATHER.get('data')
                if not v or v.get('detail') == 'bağlantı yok':
                    _S['hata'] = 1
            except Exception:
                pass
        if eski_d is not None and (duvar - eski_d) - (mono - eski_m) > UYKU_ESIGI:
            return 'uyku'
        if _S['hata']:
            bekle = min(HATA_EN_COK, HATA_ILK * (2 ** (_S['hata'] - 1)))
            return 'hata' if mono - _S['son_deneme'] >= bekle else None
        if anahtar != _S['saat']:
            return 'saat'
        try:
            q = _sorgu()[0]
        except Exception:
            q = _S['konum']
        if q != _S['konum']:
            return 'konum'
        return None


def _getir():
    """Hava verisini çeker ve panels önbelleğine yazar. Hata → istisna (önbellek bozulmaz)."""
    from . import panels
    query, place, spot = _sorgu()
    data = panels._fetch_weather(query, place, spot)
    with panels._lock:
        panels._WEATHER.update({'at': time.time(), 'data': data, 'for': query})
    return data, query


def yenile(neden: str) -> bool:
    """Havayı yeniler; panel değiştiyse (ya da saat başıysa) HUD'a basar. Başarılı mı döner."""
    mono = _mono()
    with _lock:
        _S['son_deneme'] = mono
    try:
        data, query = _getir()
    except Exception as exc:
        with _lock:
            _S['hata'] += 1
        log('ek_hava: hava alınamadı', neden, type(exc).__name__, '(yeniden denenecek)')
        return False
    with _lock:
        _S['hata'] = 0
        _S['saat'] = (_simdi().date().isoformat(), _simdi().hour)
        _S['konum'] = query
        yeni = _imza(data)
        degisti = yeni != _S['itilen']
        _S['itilen'] = yeni
        _S['sebepler'].append(neden)
        del _S['sebepler'][:-20]
    if degisti or neden in ('saat', 'uyku'):
        _it(data)
    log('ek_hava: hava yenilendi', neden, '(değişti)' if degisti else '(aynı)')
    return True


def _it(data) -> None:
    try:
        from . import ek
        a = ek.app
        if a is not None:
            a.hud.call('panel', data)
    except Exception as exc:
        log('ek_hava: panel basılamadı', type(exc).__name__)


def _dongu() -> None:
    while True:
        time.sleep(KONTROL_SN)
        try:
            if not _acik():
                continue
            n = sebep(_simdi(), _duvar(), _mono())
            if n:
                if n == 'saat':
                    time.sleep(random.uniform(1, 25))      # herkes saat başında aynı anda istek atmasın
                yenile(n)
        except Exception as exc:
            log('ek_hava: döngü hatası', type(exc).__name__, exc)


def baslat() -> None:
    """Idempotent; arka planda."""
    try:
        kur()
    except Exception as exc:
        log('ek_hava: kurulamadı', type(exc).__name__, exc)
        return
    with _lock:
        if _S['t'] is not None and _S['t'].is_alive():
            return
        t = threading.Thread(target=_dongu, daemon=True, name='ek-hava')
        _S['t'] = t
        t.start()


def durum() -> dict:
    with _lock:
        return {'kuruldu': _S['kuruldu'], 'hata': _S['hata'], 'son_sebepler': list(_S['sebepler'])}
