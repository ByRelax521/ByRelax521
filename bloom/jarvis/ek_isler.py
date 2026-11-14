"""BLOOM — arka plan işleri (ÇOKLU GÖREV) ve KAYIPSIZ TESLİM.

Neden: araştırma/konsey/kod gibi uzun işler uygulamanın 30 sn'lik araç sınırından uzun sürer. Bunlar arka plan iş parçacığında yürür; BLOOM
bu sırada başka şeyler konuşabilir, birden çok iş aynı anda çalışabilir. Bu modül üç şeyi yapar:

  1. İŞ KAYDI   her işin kimliği, durumu, ilerlemesi ve KONTROL NOKTASI (ör. araştırmada biten alt sorular) diske yazılır (ek-isler.json).
                Uygulama kapanır ya da kota yüzünden iş yarıda kalırsa kaybolmaz; `isler(eylem=devam)` kalan yerden sürdürür.
  2. KAYIPSIZ TESLİM  Asıl uygulamanın `brain.announce` işlevi oturum yokken / BLOOM uykudayken sonucu SESSİZCE atar. Burada sonuç gerçekten
                oturuma gitti mi bakılır (`announce_wait`); gitmediyse kuyrukta bekler, 15 sn'de bir yeniden denenir ve bir sonraki oturumun
                başında istem bloğuna da yazılır.
  3. `isler` aracı  liste · durum · iptal · devam.
"""

from __future__ import annotations
import json
import threading
import time
import uuid
from . import paths
from .log import log

DOSYA = 'ek-isler.json'
MAX_AKTIF = 3          # aynı anda çalışabilecek arka plan işi
MAX_KAYIT = 30
TESLIM_OMRU = 3600     # sn: teslim edilemeyen sonuç en çok bu kadar kuyrukta tutulur
TESLIM_ARALIK = 15.0

_L = threading.RLock()
ISLER: dict[str, dict] = {}
TESLIM: list[dict] = []
DEVAM: dict[str, object] = {}       # tur -> fn(is_kaydi, args) -> str
_ST = {'yuklendi': False, 'teslim_is': False, 'iptal': set()}
AKTIF_DURUMLAR = ('calisiyor', 'bekliyor')


class Dolu(RuntimeError):
    pass


def _yol():
    return paths.DATA_DIR / DOSYA


def _yukle() -> None:
    with _L:
        if _ST['yuklendi']:
            return
        _ST['yuklendi'] = True
        try:
            d = json.loads(_yol().read_text('utf-8'))
            for k in d.get('isler', []):
                if isinstance(k, dict) and k.get('id'):
                    if k.get('durum') in AKTIF_DURUMLAR:     # önceki oturumda çalışıyordu → yarım
                        k['durum'] = 'yarim'
                        k['ilerleme'] = 'uygulama kapandığı için yarıda kaldı (kalan yerden sürdürülebilir)'
                    ISLER[k['id']] = k
            for t in d.get('teslim', []):
                if isinstance(t, dict) and time.time() - float(t.get('ts', 0)) < TESLIM_OMRU:
                    TESLIM.append(t)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log('ek_isler: kayıt okunamadı', type(exc).__name__, str(exc)[:80])


def _kaydet() -> None:
    try:
        with _L:
            sirali = sorted(ISLER.values(), key=lambda k: k.get('olusma', 0))[-MAX_KAYIT:]
            kalan = {x['id'] for x in sirali}
            for k in list(ISLER):
                if k not in kalan:
                    ISLER.pop(k, None)
            veri = {'isler': sirali, 'teslim': TESLIM[-20:]}
            p = _yol()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix('.tmp')
            tmp.write_text(json.dumps(veri, ensure_ascii=False), 'utf-8')
            tmp.replace(p)
    except Exception as exc:
        log('ek_isler: kayıt yazılamadı', type(exc).__name__, str(exc)[:80])


def _yeni_id() -> str:
    return 'is-' + uuid.uuid4().hex[:6]


def yeni(tur: str, baslik: str, parametre: dict | None = None) -> dict:
    _yukle()
    with _L:
        if len([k for k in ISLER.values() if k.get('durum') in AKTIF_DURUMLAR]) >= MAX_AKTIF:
            raise Dolu(f'Aynı anda en fazla {MAX_AKTIF} arka plan işi çalışabilir; biri bitince ya da isler(eylem=iptal) ile yenisini başlat.')
        k = {'id': _yeni_id(), 'tur': tur, 'baslik': str(baslik)[:100], 'durum': 'calisiyor', 'ilerleme': 'başladı', 'olusma': time.time(),
             'guncelleme': time.time(), 'sonuc': '', 'parametre': parametre or {}, 'kontrol': {}}
        ISLER[k['id']] = k
        _kaydet()
        return k


def al(is_id: str) -> dict | None:
    _yukle()
    return ISLER.get(is_id)


def guncelle(is_id: str, **kw) -> None:
    with _L:
        k = ISLER.get(is_id)
        if not k:
            return
        k.update(kw)
        k['guncelleme'] = time.time()
        _kaydet()


def olay(is_id: str, metin: str) -> None:
    """İşin teşhis günlüğüne (son 20) zamanlı satır ekler; art arda aynı satır tekrarlanmaz."""
    with _L:
        k = ISLER.get(is_id)
        if not k:
            return
        o = k.setdefault('olaylar', [])
        m = ' '.join(str(metin).split())[:230]
        if o and o[-1].get('m') == m:
            return
        o.append({'t': time.time(), 'm': m})
        del o[:-20]
        k['guncelleme'] = time.time()
        _kaydet()


def kontrol_yaz(is_id: str, kontrol: dict) -> None:
    guncelle(is_id, kontrol=kontrol)


def iptal_istendi(is_id: str) -> bool:
    return is_id in _ST['iptal']


def bitir(is_id: str, durum: str, sonuc: str = '', ilerleme: str = '') -> None:
    _ST['iptal'].discard(is_id)
    guncelle(is_id, durum=durum, sonuc=str(sonuc)[:1500],
             ilerleme=ilerleme or {'bitti': 'tamamlandı', 'yarim': 'yarıda kaldı', 'hata': 'hata', 'iptal': 'iptal edildi'}.get(durum, durum))


def aktifler(tur: str | None = None) -> list[dict]:
    _yukle()
    return [k for k in ISLER.values() if k.get('durum') in AKTIF_DURUMLAR and (tur is None or k.get('tur') == tur)]


# --------------------------------------------------------------------------- kayıpsız teslim
def _gonder(metin: str) -> bool:
    """Not oturuma GERÇEKTEN gitti mi? (announce_wait yoksa announce'a güvenilir.)"""
    from . import ek
    brain = getattr(ek.app, 'brain', None)
    if brain is None:
        return False
    try:
        if hasattr(brain, 'announce_wait'):
            return bool(brain.announce_wait(metin, 10.0))
        brain.announce(metin)
        return True
    except Exception as exc:
        log('ek_isler: teslim denemesi başarısız', type(exc).__name__, str(exc)[:80])
        return False


def teslim_et(anahtar: str, metin: str) -> bool:
    """Sonucu BLOOM'a söyletir. Şu an olmuyorsa kuyruğa alır (15 sn'de bir dener; sonraki oturumda istemde de görünür). Döner: hemen gitti mi."""
    _yukle()
    if _gonder(metin):
        return True
    with _L:
        TESLIM.append({'anahtar': anahtar, 'not': metin, 'ts': time.time(), 'deneme': 1})
        _kaydet()
        calisiyor = _ST['teslim_is']
        _ST['teslim_is'] = True
    if not calisiyor:
        threading.Thread(target=_teslim_dongusu, daemon=True, name='ek-teslim').start()
    return False


def _teslim_dongusu() -> None:
    try:
        while True:
            time.sleep(TESLIM_ARALIK)
            with _L:
                bekleyen = list(TESLIM)
            if not bekleyen:
                break
            for t in bekleyen:
                if time.time() - float(t.get('ts', 0)) > TESLIM_OMRU:
                    with _L:
                        if t in TESLIM:
                            TESLIM.remove(t)
                    continue
                if _gonder(t['not']):
                    with _L:
                        if t in TESLIM:
                            TESLIM.remove(t)
                        _kaydet()
                else:
                    t['deneme'] = int(t.get('deneme', 1)) + 1
    finally:
        with _L:
            _ST['teslim_is'] = False


def teslim_bekleyen() -> list[dict]:
    _yukle()
    return list(TESLIM)


# --------------------------------------------------------------------------- istem + araç
def _gecen(ts: float) -> str:
    s = max(0, int(time.time() - ts))
    return f'{s} sn' if s < 90 else (f'{s // 60} dk' if s < 5400 else f'{s // 3600} sa')


def istem_blogu() -> str:
    """Oturum başında: çalışan işler, teslim edilemeyen sonuçlar, yarım kalanlar."""
    try:
        _yukle()
        satir = []
        for k in ISLER.values():
            if k.get('durum') in AKTIF_DURUMLAR:
                satir.append(f'- ÇALIŞIYOR [{k["id"]}] {k["tur"]}: {k["baslik"]} — {k.get("ilerleme", "")} ({_gecen(k["olusma"])} önce başladı)')
        with _L:
            bekleyen = list(TESLIM)
            TESLIM.clear()      # istem bloğuna giriyor: aynı sonuç ikinci kez duyurulmasın
            if bekleyen:
                _kaydet()
        for t in bekleyen:
            satir.append(f'- BİTTİ, KULLANICIYA HENÜZ SÖYLENMEDİ: {str(t["not"])[:1200]}')
        yarim = [k for k in ISLER.values() if k.get('durum') == 'yarim' and time.time() - k.get('guncelleme', 0) < 6 * 3600]
        for k in yarim[-3:]:
            satir.append(f'- YARIM KALDI [{k["id"]}] {k["tur"]}: {k["baslik"]} — {k.get("ilerleme", "")} (isler(eylem=devam) ile sürdürülür)')
        if not satir:
            return ''
        return '[ARKA PLAN İŞLERİN — aynı anda birden çok iş sürebilir; durum için isler aracı]\n' + '\n'.join(satir[:8])
    except Exception:
        return ''


def _ozet(k: dict) -> str:
    d = {'calisiyor': 'çalışıyor', 'bekliyor': 'bekliyor', 'bitti': 'bitti', 'yarim': 'yarım kaldı', 'hata': 'hata', 'iptal': 'iptal'}.get(k.get('durum'), k.get('durum'))
    return f'[{k["id"]}] {k["tur"]} “{k["baslik"]}” — {d}: {k.get("ilerleme", "")} ({_gecen(k.get("olusma", time.time()))} önce)'


def _bul(a: dict, durumlar=None) -> dict | None:
    _yukle()
    kimlik = str(a.get('is_id') or '').strip()
    if kimlik:
        return ISLER.get(kimlik)
    adaylar = [k for k in ISLER.values() if durumlar is None or k.get('durum') in durumlar]
    adaylar.sort(key=lambda k: k.get('olusma', 0))
    return adaylar[-1] if adaylar else None


def _teshis(k: dict) -> str:
    """Gerçek durum ayrıntısı: model, son olaylar, sessizlik süresi. Model bu bilgilerin dışında NEDEN uydurmamalı."""
    satir = ['GERÇEK AYRINTI (yalnız bunlara dayan; \"sistem yoğun\" gibi tahmin söyleme):']
    sess = int(time.time() - k.get('guncelleme', time.time()))
    satir.append(f'- son hareket {sess} sn önce' + (' — uzun süredir ilerleme yok' if k.get('durum') in AKTIF_DURUMLAR and sess > 150 else ''))
    try:
        from . import ek_model
        satir.append('- ' + ek_model.son_model())
    except Exception:
        pass
    kt = k.get('kontrol') or {}
    if isinstance(kt, dict) and kt.get('sorular'):
        satir.append(f'- alt sorular: {len(kt.get("bulgular", []))}/{len(kt["sorular"])} tamam' + (' (günlük kota doldu)' if kt.get('gunluk') else ''))
    ol = k.get('olaylar') or []
    if ol:
        satir.append('- son olaylar:')
        for e in ol[-12:]:
            satir.append(f'  · {time.strftime("%H:%M:%S", time.localtime(e.get("t", 0)))} {e.get("m", "")}')
    else:
        satir.append('- kayıtlı olay yok (iş henüz bir şey bildirmedi)')
    return '\n'.join(satir)


def arac(a: dict, _c=None) -> str:
    a = a or {}
    eylem = str(a.get('eylem') or 'liste').lower()
    _yukle()
    if eylem == 'liste':
        if not ISLER:
            return 'Arka planda çalışan ya da kayıtlı iş yok.'
        ks = sorted(ISLER.values(), key=lambda k: k.get('olusma', 0), reverse=True)[:12]
        return f'{len(aktifler())} iş çalışıyor; kayıtlı {len(ISLER)} iş:\n' + '\n'.join(_ozet(k) for k in ks)
    if eylem == 'durum':
        k = _bul(a)
        if not k:
            return 'Böyle bir iş yok.'
        s = _ozet(k)
        if k.get('sonuc'):
            s += '\nSonuç özeti: ' + k['sonuc']
        s += '\n' + _teshis(k)
        return s
    if eylem == 'iptal':
        k = _bul(a, AKTIF_DURUMLAR)
        if not k or k.get('durum') not in AKTIF_DURUMLAR:
            return 'İptal edilecek çalışan iş yok.'
        _ST['iptal'].add(k['id'])
        guncelle(k['id'], ilerleme='iptal isteniyor…')
        return f'“{k["baslik"]}” işi iptal ediliyor (birkaç saniye içinde durur).'
    if eylem == 'devam':
        k = _bul(a, ('yarim', 'hata'))
        if not k or k.get('durum') not in ('yarim', 'hata'):
            return 'Sürdürülecek yarım kalmış iş yok.'
        fn = DEVAM.get(k.get('tur'))
        if fn is None and k.get('tur') == 'arastirma':
            from . import ek
            fn = ek._arastirma_devam
        if fn is None and k.get('tur') == 'kod':
            from . import ek_kod
            fn = ek_kod.devam
        if fn is None:
            return f'Bu iş türü ({k.get("tur")}) sürdürülemiyor.'
        return fn(k, a)
    return 'Bilinmeyen eylem. Geçerli: liste, durum, iptal, devam.'
