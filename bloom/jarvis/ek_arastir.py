"""BLOOM — derin araştırma hattı.

Eskiden araştırma TEK bir Google aramalı model çağrısıydı: "en fazla 4 cümle" (derin: 8 cümle) ya da tek seferde yazılan bir rapor.
Bu yüzden yüzeysel kalıyordu. Şimdi gerçek bir hat var:

  1. PLAN      soru 3-6 bağımsız alt soruya bölünür (tanım/durum, sayılar-tarihler, karşı görüşler, riskler, güncel gelişmeler…)
  2. ARAMA     her alt soru için AYRI bir Google aramalı çağrı, paralel; her biri ayrıntılı "bulgu" notu yazar
  3. DENETİM   (ayrıntılı seviye) bulguların boşluğu/çelişkisi aranır, en çok 2 ek alt soru aranır
  4. SENTEZ    tüm bulgular tek raporda birleştirilir; sayılar/tarihler korunur, çelişki gizlenmez, kaynak numaraları verilir

Seviyeler:  standart → 3 alt soru, 450-900 kelime  |  ayrintili → 6 alt soru + denetim, 1800-3500 kelime.
Hat ek.py'deki iki ilkele dayanır (testlerde değiştirilebilsin diye çalışma anında ek üzerinden çağrılır):
  ek._grounded(soru, derin, uzun=False, bulgu=False) -> (metin, [{'baslik','url'}])
  ek._uret_metin(sistem, icerik, json=False, max_token=..., zaman_ms=...) -> metin
"""

from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import json
import re
import threading
import time
from .log import log

SEVIYE = {      # 'zaman': tüm hat (sn); limitte beklemeler dahil. 'arama_sn': tek alt sorunun yeniden deneme bütçesi; 'sentez_sn': sentezinki
    'standart': {'alt': 3, 'denetim': False, 'min_kelime': 450, 'max_kelime': 900, 'token': 5000, 'zaman': 480.0, 'arama_sn': 300.0, 'sentez_ms': 90000, 'sentez_sn': 180.0},
    'ayrintili': {'alt': 6, 'denetim': True, 'min_kelime': 1800, 'max_kelime': 3500, 'token': 14000, 'zaman': 1080.0, 'arama_sn': 420.0, 'sentez_ms': 170000, 'sentez_sn': 300.0},
}
ALT_ARAMA_SN = 80.0
MAX_KAYNAK = 24

PLAN_TALIMAT = ('Sen bir araştırma planlayıcısısın. Kullanıcının sorusunu cevaplamak için İNTERNETTE ayrı ayrı aranacak, birbirini TEKRAR ETMEYEN '
                '{n} alt soru üret. Alt sorular birbirinden farklı yönleri kapsasın: temel olgular/tanım, güncel durum ve son gelişmeler, sayılar-tarihler-fiyatlar, '
                'karşılaştırma/alternatifler, riskler-karşı görüşler-eleştiriler, (uygunsa) uzman/resmî kaynak görüşü. Her alt soru kendi başına arama kutusuna '
                'yazılabilecek açıklıkta, Türkçe (gerekiyorsa yabancı terimle) olsun. Bugünün tarihi: {now}. '
                'Yalnızca JSON döndür: {{"alt_sorular": ["...", "..."]}}')
BOSLUK_TALIMAT = ('Sen titiz bir araştırma denetçisisin. Aşağıda bir ana soru ve şimdiye kadar toplanan bulgular var. Eksik kalan önemli bir yönü, bulgular arasındaki '
                  'ÇELİŞKİYİ ya da doğrulanmamış kritik bir iddiayı bulursan, onu çözecek en çok {n} yeni alt soru yaz. Her şey yeterliyse boş liste ver. '
                  'Yalnızca JSON döndür: {{"alt_sorular": ["..."]}}')
SENTEZ_TALIMAT = ('Sen titiz, dürüst bir araştırma analistisin. Aşağıdaki BULGU bölümlerini (her biri ayrı bir Google aramasının sonucu) tek, bütünlüklü, '
                  'ayrıntılı bir RAPORDA birleştir. Türkçe yaz. Uzunluk: en az {min_k}, en fazla {max_k} kelime; kısa kesme. '
                  'Yapı (başlıkları BÜYÜK HARFLE yaz): ÖZET (4-6 cümle: asıl cevap) · ANA BULGULAR (konu başlıklarıyla, ayrıntılı) · '
                  'SAYILAR, TARİHLER, KARŞILAŞTIRMA · FARKLI GÖRÜŞLER, ÇELİŞKİLER VE BELİRSİZLİKLER · SONUÇ VE ÖNERİ · NEYİ DOĞRULAMALI. '
                  'KURALLAR: Yalnızca bulgularda yazan bilgiyi kullan; kendi bilginden olgu ekleme, sayı/tarih/ad uydurma. Bölümler çelişiyorsa ikisini de yaz ve '
                  'çelişkiyi açıkça belirt. Emin olunmayan her şeyi "doğrulanmadı" diye işaretle. Bir olgunun hangi kaynaklardan geldiğini cümlenin sonunda köşeli parantezle '
                  'ver, örn. [3] ya da [2,5]; numaralar yalnızca o BULGU bölümünün "Kaynaklar" satırındaki numaralardır. '
                  'DÜZ METİN yaz: Markdown işareti (**, #, tablo, ```) kullanma; maddeleri "- " ile ver. Bugünün tarihi: {now}.')
BULGU_TALIMAT = ('Sen bir araştırma yardımcısısın. Verilen soruyu Google aramasıyla DERİNLEMESİNE araştır ve bulgularını AYRINTILI bir not olarak yaz '
                 '(250-450 kelime). Türkçe yaz. Somut ol: sayılar, tarihler, adlar, birimler, fiyatlar, sürümler, kaynak kuruluşlar. Birden fazla kaynağı karşılaştır; '
                 'kaynaklar çelişiyorsa ikisini de ve farkı yaz. Yalnızca kaynaklarda desteklenen bilgiyi ver; bulamadığını "bulunamadı" de, tahmin yürütme. '
                 'Düz metin: Markdown işareti kullanma, maddeleri "- " ile ver. Bugünün tarihi: {now}.')


def _ek():
    from . import ek
    return ek


def _simdi() -> str:
    return dt.datetime.now().strftime('%d.%m.%Y %H:%M')


def _json(raw: str):
    s = str(raw or '').strip()
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s)
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r'\{.*\}', s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _temiz_sorular(liste, soru: str, n: int) -> list[str]:
    out, goruldu = [], {re.sub(r'\W+', ' ', soru.lower()).strip()}
    for q in liste if isinstance(liste, list) else []:
        q = ' '.join(str(q or '').split())[:240]
        k = re.sub(r'\W+', ' ', q.lower()).strip()
        if len(q) >= 8 and k not in goruldu:
            goruldu.add(k)
            out.append(q)
    return out[:n]


def varsayilan_plan(soru: str, n: int) -> list[str]:
    """Model planı vermezse: ana soru + genel bakış açıları."""
    ekler = ['{s} güncel durum ve son gelişmeler', '{s} sayılar, tarihler, fiyatlar ve karşılaştırma', '{s} riskler, eleştiriler ve karşı görüşler',
             '{s} uzman ve resmî kaynak görüşleri', '{s} alternatifler ve öneriler']
    return [soru] + [e.format(s=soru) for e in ekler[:max(0, n - 1)]]


def plan_yap(soru: str, n: int) -> list[str]:
    ek = _ek()
    try:
        ham = ek._uret_metin(PLAN_TALIMAT.format(n=n, now=_simdi()), soru, json=True, max_token=900, zaman_ms=25000)
        d = _json(ham) or {}
        sorular = _temiz_sorular(d.get('alt_sorular'), soru, n)
    except Exception as exc:
        log('ek_arastir: plan alınamadı', type(exc).__name__, str(exc)[:120])
        sorular = []
    if len(sorular) < 2:
        sorular = varsayilan_plan(soru, n)
    elif soru not in sorular and len(sorular) < n:
        sorular.insert(0, soru)
    return sorular[:n]


class Yarim(RuntimeError):
    """Kota/limit yüzünden bitmedi; bulgular kontrol noktasında saklı, `devam` kalan yerden sürdürür."""

    def __init__(self, mesaj: str, eksik: list[str] | None = None, gunluk: bool = False, asama: str = 'arama'):
        super().__init__(mesaj)
        self.eksik, self.gunluk, self.asama = list(eksik or []), gunluk, asama


class Iptal(RuntimeError):
    pass


BEKLE_CARPAN = 1.0      # testlerde küçültülür
ESZAMAN = 2             # aynı anda en çok bu kadar arama (ücretsiz kotada 429'u azaltır)


def hata_turu(exc: Exception) -> str:
    """'gunluk' (günlük kota) · 'limit' (dakikalık limit/429, beklemekle geçer) · 'kalici' (anahtar/istek hatası) · 'gecici' (ağ/zaman aşımı/5xx)."""
    s = (type(exc).__name__ + ' ' + str(exc)).lower()
    kota = '429' in s or 'resource_exhausted' in s or 'quota' in s or ('rate' in s and 'limit' in s)
    if kota and any(k in s for k in ('perday', 'per day', 'per_day', 'daily')):
        return 'gunluk'
    if kota:
        return 'limit'
    if re.search(r'\b(400|401|403)\b', s) or 'api key' in s or 'api_key' in s or 'permission_denied' in s or 'anahtar yok' in s or 'anahtarı yok' in s:
        return 'kalici'
    return 'gecici'


def bekleme_suresi(exc: Exception, deneme: int) -> float:
    """Sunucu 'retry in 21s' diyorsa onu, demiyorsa 10-20-40-60 sn."""
    s = str(exc)
    m = re.search(r'retry(?:Delay)?\D{0,20}?(\d+(?:\.\d+)?)\s*s', s, re.I)
    if m:
        return min(90.0, float(m.group(1)) + 2.0)
    return float(min(60, 10 * (2 ** max(0, deneme - 1))))


def _uyu(sn: float, iptal=None) -> None:
    son = time.monotonic() + sn * BEKLE_CARPAN
    while time.monotonic() < son:
        if iptal and iptal():
            raise Iptal('iptal edildi')
        time.sleep(min(0.5, max(0.005, son - time.monotonic())))


def _dene(fn, toplam_sn: float, iptal=None, haber=None, etiket: str = ''):
    """fn()'i dener; limit/geçici hatada bekleyip yeniden dener (en çok `toplam_sn` boyunca). Kalıcı hatada ve günlük kotada vazgeçer.
    Başarısızlıkta SON istisnayı fırlatır (tür: hata_turu)."""
    bitis = time.monotonic() + toplam_sn
    deneme = 0
    gunluk_deneme = 0
    while True:
        if iptal and iptal():
            raise Iptal('iptal edildi')
        try:
            return fn()
        except Iptal:
            raise
        except Exception as exc:
            deneme += 1
            tur = hata_turu(exc)
            ozet = f'{etiket or "istek"}: {type(exc).__name__} {" ".join(str(exc).split())[:90]}'

            def _vazgec(neden):
                if haber:
                    try:
                        haber(f'VAZGEÇİLDİ ({neden}; tür={tur}, {deneme}. deneme) — {ozet}')
                    except Exception:
                        pass
            if tur == 'kalici':
                _vazgec('kalıcı hata')
                raise
            if tur == 'gunluk':
                gunluk_deneme += 1
                if gunluk_deneme >= 2:
                    _vazgec('günlük kota doldu')
                    raise
            if tur == 'gecici' and deneme >= 4:
                _vazgec('ağ/geçici hata 4 kez sürdü')
                raise
            bekle = 45.0 if tur == 'gunluk' else bekleme_suresi(exc, deneme)
            if time.monotonic() + bekle * BEKLE_CARPAN > bitis or deneme >= 12:
                _vazgec('süre bütçesi bitti' if deneme < 12 else '12 deneme doldu')
                raise
            log('ek_arastir: yeniden denenecek', etiket, tur, f'{bekle:.0f} sn', str(exc)[:80])
            if haber:
                haber(('limit' if tur in ('limit', 'gunluk') else 'ag') + f': {bekle:.0f} sn bekleniyor ({deneme}. deneme) — {ozet}')
            _uyu(bekle, iptal)


def _bulgu_ara(alt: str):
    ek = _ek()
    metin, kaynaklar = ek._grounded(alt, True, False, True)
    return str(metin or '').strip(), list(kaynaklar or [])


def _tamam(durum: dict) -> set:
    return {b['soru'] for b in durum['bulgular']}


def _arama_turu(sorular: list[str], durum: dict, toplam_sn: float, son: float, iptal, haber, kaydet) -> None:
    """Alt soruları (en çok ESZAMAN paralel) arar; her biri LİMİTTE BEKLEYİP yeniden denenir. Biten bulgu hemen kontrol noktasına yazılır.
    Başarısız sorular durum['eksik'] içinde kalır; günlük kota doluysa durum['gunluk']=True olur ve yenisi başlatılmaz."""
    bekleyen = [q for q in sorular if q not in _tamam(durum)]
    if not bekleyen:
        return
    kilit = threading.Lock()
    kuyruk = list(bekleyen)

    def isci():
        while True:
            with kilit:
                if not kuyruk or durum.get('gunluk') or (iptal and iptal()) or time.monotonic() > son:
                    return
                q = kuyruk.pop(0)
            try:
                metin, kay = _dene(lambda: _bulgu_ara(q), min(toplam_sn, max(5.0, son - time.monotonic())), iptal, haber, 'arama')
                if len(metin) < 80:
                    raise RuntimeError('arama boş sonuç verdi')
            except Iptal:
                return
            except Exception as exc:
                tur = hata_turu(exc)
                log('ek_arastir: alt arama başarısız', tur, type(exc).__name__, str(exc)[:100])
                if tur == 'gunluk':
                    durum['gunluk'] = True
                durum['sonuncu_hata'] = f'{tur}: {str(exc)[:120]}'
                continue
            with kilit:
                durum['bulgular'].append({'soru': q, 'metin': metin, 'kaynaklar': kay})
                kaydet()
                haber(f'{len(durum["bulgular"])}/{len(durum["sorular"])} alt soru araştırıldı')

    th = [threading.Thread(target=isci, daemon=True, name='ek-arastir') for _ in range(min(ESZAMAN, len(bekleyen)))]
    for i, x in enumerate(th):
        x.start()
        time.sleep(0.2 * BEKLE_CARPAN * (i + 1))     # istekler aynı anda patlamasın
    for x in th:
        x.join()
    if iptal and iptal():
        raise Iptal('iptal edildi')


def kaynaklari_numarala(bulgular: list[dict]) -> list[dict]:
    """Bulgulardaki kaynakları adrese göre tekilleştirip 1'den numaralar; her bulguya 'no' listesi yazar. Döner: [{'no','baslik','url'}]."""
    tum: list[dict] = []
    idx: dict[str, int] = {}
    for b in bulgular:
        b['no'] = []
        for k in b['kaynaklar']:
            url = str(k.get('url') or '')
            if not url:
                continue
            if url not in idx:
                if len(tum) >= MAX_KAYNAK:
                    continue
                tum.append({'no': len(tum) + 1, 'baslik': str(k.get('baslik') or ''), 'url': url})
                idx[url] = len(tum)
            if idx.get(url) and idx[url] not in b['no']:
                b['no'].append(idx[url])
    return tum


def _bulgu_metni(bulgular: list[dict]) -> str:
    parcalar = []
    for i, b in enumerate(bulgular, 1):
        nolar = ', '.join(str(n) for n in b.get('no', [])) or 'kaynak listesi yok'
        parcalar.append(f'BULGU {i} — Alt soru: {b["soru"]}\nKaynaklar: {nolar}\n{b["metin"]}')
    return '\n\n'.join(parcalar)


def calistir(soru: str, seviye: str = 'standart', ilerleme=None, kontrol: dict | None = None, kaydet=None, iptal=None, kismi: bool = False) -> dict:
    """Hattı çalıştırır. `kontrol` (kontrol noktası) verilirse kalan yerden sürer; her adım sonrası `kaydet()` çağrılır; `iptal()` True ise Iptal.
    Döner: {'rapor','kaynaklar','alt_sorular','bulgu_sayisi','basarisiz','eksik','sure','seviye','sentezlendi'}.
    Hiç bulgu yoksa ya da kota yüzünden bitemezse `Yarim`/istisna (bulgular kontrol noktasında kalır)."""
    ek = _ek()
    s = SEVIYE.get(seviye) or SEVIYE['standart']
    t0 = time.time()
    son = time.monotonic() + s['zaman']
    durum = kontrol if isinstance(kontrol, dict) else {}
    durum.setdefault('sorular', [])
    durum.setdefault('bulgular', [])
    durum.pop('gunluk', None)
    kaydet_ = kaydet or (lambda: None)

    def haber(m):
        if ilerleme:
            try:
                ilerleme(m)
            except Exception:
                pass

    if not durum['sorular']:
        haber('plan')
        durum['sorular'] = plan_yap(soru, s['alt'])
        kaydet_()
    haber('arama')
    _arama_turu(durum['sorular'], durum, s['arama_sn'], son, iptal, haber, kaydet_)
    bulgular = durum['bulgular']
    if not bulgular:
        tur_ = str(durum.get('sonuncu_hata') or '').split(':')[0]
        if tur_ in ('limit', 'gunluk'):
            raise Yarim('hiçbir alt arama sonuç vermedi: ' + str(durum.get('sonuncu_hata')), durum['sorular'], tur_ == 'gunluk', 'arama')
        raise RuntimeError('hiçbir alt arama sonuç vermedi: ' + str(durum.get('sonuncu_hata') or 'bilinmiyor'))
    if s['denetim'] and not durum.get('denetim') and len(bulgular) >= 2 and not (set(durum['sorular']) - _tamam(durum)) and time.monotonic() < son - 90:
        haber('denetim')
        try:
            ham = _dene(lambda: ek._uret_metin(BOSLUK_TALIMAT.format(n=2), f'ANA SORU: {soru}\n\n' + _bulgu_metni(bulgular)[:24000], json=True, max_token=600, zaman_ms=30000),
                        90, iptal, haber, 'denetim')
            ek_sorular = _temiz_sorular((_json(ham) or {}).get('alt_sorular'), soru, 2)
            ek_sorular = [q for q in ek_sorular if q not in durum['sorular']]
        except Iptal:
            raise
        except Exception as exc:
            log('ek_arastir: boşluk denetimi atlandı', type(exc).__name__, str(exc)[:100])
            ek_sorular = []
        durum['denetim'] = True
        if ek_sorular:
            haber('ek-arama')
            durum['sorular'] = durum['sorular'] + ek_sorular
            kaydet_()
            _arama_turu(ek_sorular, durum, s['arama_sn'], son, iptal, haber, kaydet_)
        else:
            kaydet_()
    eksik = [q for q in durum['sorular'] if q not in _tamam(durum)]
    if eksik and s['denetim'] and not kismi:
        raise Yarim(f'{len(bulgular)}/{len(durum["sorular"])} alt soru araştırılabildi; kalanlar limit/kota yüzünden yapılamadı', eksik, bool(durum.get('gunluk')), 'arama')
    kaynaklar = kaynaklari_numarala(bulgular)
    haber('sentez')
    talimat = SENTEZ_TALIMAT.format(min_k=s['min_kelime'], max_k=s['max_kelime'], now=_simdi())
    icerik = f'ANA SORU: {soru}\n\n' + _bulgu_metni(bulgular)
    limit_hatasi = None
    try:
        rapor = str(_dene(lambda: ek._uret_metin(talimat, icerik, json=False, max_token=s['token'], zaman_ms=s['sentez_ms']),
                          s['sentez_sn'], iptal, haber, 'sentez') or '').strip()
    except Iptal:
        raise
    except Exception as exc:
        log('ek_arastir: sentez başarısız', type(exc).__name__, str(exc)[:120])
        rapor = ''
        if hata_turu(exc) in ('limit', 'gunluk'):
            limit_hatasi = exc
    if limit_hatasi is not None and s['denetim'] and not kismi:     # ayrıntılıda ham bulguyu rapor diye sunma: bulgular saklı, sentez sonra yapılır
        raise Yarim('bulgular tamam ama rapor yazımı limit yüzünden bekliyor', [], hata_turu(limit_hatasi) == 'gunluk', 'sentez')
    sentezlendi = len(rapor) >= 200
    if not sentezlendi:       # sentez çökerse bulguların kendisi rapordur: hiçbir şey kaybolmaz
        rapor = 'ÖZET (sentez yapılamadı; ham bulgular aşağıda)\n\n' + '\n\n'.join(f'{b["soru"].upper()}\n{b["metin"]}' for b in bulgular)
    return {'rapor': rapor, 'kaynaklar': kaynaklar, 'alt_sorular': durum['sorular'], 'bulgu_sayisi': len(bulgular), 'basarisiz': len(eksik), 'eksik': eksik,
            'sure': time.time() - t0, 'seviye': seviye, 'sentezlendi': sentezlendi}


def kaynakca_metni(kaynaklar: list[dict]) -> str:
    return '\n'.join(f'[{k["no"]}] {k["baslik"] or k["url"]} — {k["url"]}' for k in kaynaklar)
