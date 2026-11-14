"""BLOOM EK — KONSEY: birden çok yapay zekânın bağımsız görüş verip birbirini eleştirdiği, sonra ortak karar çıkardığı araç.

ÜCRETSİZ çalışır:
  · Anahtarsız temel: Gemini'nin ücretsiz katmanı (zaten kurulu anahtar) — üç ayrı ROL (rasyonel analist, şüpheci denetçi,
    uygulayıcı) + hakem. Aynı model olduğu için çeşitlilik rollerden gelir; bunu sonuçta dürüstçe belirtir.
  · İsteğe bağlı gerçek çeşitlilik: Groq, OpenRouter (ücretsiz ":free" modeller), Mistral, NVIDIA NIM ya da herhangi bir OpenAI uyumlu
    servis. Anahtarlar BLOOM › PANEL › KONSEY'den girilir, Windows Kimlik Bilgisi Yöneticisi'nde (keyring) saklanır.
Akış:  1) herkes bağımsız görüş verir (JSON: öneri, gerekçe, güven, risk, seçenek)  2) görüşler ayrışıyorsa (ya da derin=true) herkes
diğerlerini görüp kendi görüşünü SORGULAR (çoğunluğa uymak için fikir değiştirmek yasak)  3) oylar kodla sayılır (modele bırakılmaz)
4) hakem, karşı görüşü de içeren ortak karar yazar; hakem çökerse kodla çıkarılan karar kullanılır.
GİZLİLİK: sorunun metni (ve verilen bağlam) üyelerin servislerine gider; kullanıcıya bu söylenir, gizli veri gönderilmez.
"""

from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import json
import re
import statistics
import threading
import time
from . import settings
from .log import log

SAGLAYICILAR = {
    'groq': {'ad': 'Groq', 'url': 'https://api.groq.com/openai/v1', 'anahtar_url': 'https://console.groq.com/keys',
             'modeller': ('openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'openai/gpt-oss-20b'),
             'not': 'Ücretsiz katman: dakikada 30, günde ~1000 istek (model başına).'},
    'openrouter': {'ad': 'OpenRouter', 'url': 'https://openrouter.ai/api/v1', 'anahtar_url': 'https://openrouter.ai/keys',
                   'modeller': ('openrouter/free',), 'ucretsiz_son_ek': ':free',
                   'not': 'Yalnızca ":free" modeller kullanılır: günde ~50 istek. Bazı ücretsiz modeller istemleri kaydedebilir.'},
    'mistral': {'ad': 'Mistral', 'url': 'https://api.mistral.ai/v1', 'anahtar_url': 'https://console.mistral.ai/api-keys',
                'modeller': ('mistral-small-latest', 'mistral-medium-latest', 'mistral-large-latest'),
                'not': 'Ücretsiz modda istemler model eğitiminde kullanılabilir (Mistral ayarından kapatılabilir).'},
    'nvidia': {'ad': 'NVIDIA NIM', 'url': 'https://integrate.api.nvidia.com/v1', 'anahtar_url': 'https://build.nvidia.com',
               'modeller': ('openai/gpt-oss-120b', 'meta/llama-3.3-70b-instruct'),
               'not': 'Prototip için ücretsiz erişim (yayınlanmış sabit kota yok).'},
}
TUR1_SN = 50.0               # her tur için üst sınır; yavaş üye beklenmeden bırakılır
TUR2_SN = 40.0
KONSEY_BEKLE = 22.0          # sn: araç çağrısı en çok bu kadar bekler (uygulamanın araç sınırı 30 sn); sürerse arka planda biter ve duyurulur
OZEL = 'ozel'                # kullanıcının girdiği herhangi bir OpenAI uyumlu uç nokta
ROL_SIRASI = ('rasyonel', 'supheci', 'uygulayici')
ROLLER = {
    'rasyonel': ('Rasyonel analist', 'Sen RASYONEL ANALİSTSİN: soruyu parçala, olguyu varsayımdan ayır, ölçülebilir ölçütlerle değerlendir ve net bir öneri ver.'),
    'supheci': ('Şüpheci denetçi', 'Sen ŞÜPHECİ DENETÇİSİN: akla gelen en olası yanıta KARŞI argüman üret; gizli varsayımları, kanıtsız iddiaları, riskleri ve olası hataları bul. '
                                   'Hemen katılma; ancak gerçekten sağlam çıkıyorsa bunu açıkça söyle.'),
    'uygulayici': ('Uygulayıcı', 'Sen UYGULAYICISIN: öneriyi pratik adımlara, maliyete, süreye ve geri alınabilirliğe indir; en az pişmanlık bırakan yolu seç.'),
}
ORTAK = ('Türkçe yaz. Bilmediğini UYDURMA; kanıtın/bilgin yetersizse "bilmiyorum": true de ve neyin eksik olduğunu söyle. '
         'Yalnızca JSON döndür: {{"oneri": "en çok 2 cümle", "gerekce": "en çok 4 kısa madde, tek metin", "guven": 0-100, '
         '"risk": "tek cümle", "secenek": "soru seçmeliyse seçtiğin seçenek (kısa etiket, ör. A / evet), değilse boş", "bilmiyorum": false}}. '
         'Bugünün tarihi: {bugun}.')
TUR2 = ('\n\nDİĞER ÜYELERİN GÖRÜŞLERİ:\n{digerleri}\n\nŞimdi kendi görüşünü SORGULA: ikna edici bir karşı argüman ya da yeni bir olgu gördüysen görüşünü değiştir, '
        'yoksa gerekçeyle koru. ÇOĞUNLUĞA UYMAK için fikir değiştirme. Aynı JSON biçimine iki alan ekle: "degisti": true/false, "neden": "kısa".')
HAKEM = ('Sen konseyin HAKEMİSİN. Aşağıda bir soru ve üyelerin son görüşleri var. Tarafsız bir ortak karar yaz. Yalnızca JSON: '
         '{{"sonuc": "net karar, en çok 3 cümle", "neden": "kısa gerekçe", "karsi_gorus": "en güçlü itiraz ve neden kabul/ret edildi", '
         '"dogrulanacak": "karar verilmeden önce doğrulanması gereken şey ya da boş", "guven": 0-100, "sonraki_adim": "tek somut adım"}}. '
         'Üyeler arasında gerçek anlaşmazlık varsa bunu gizleme. Bilgi yetersizse karar verme, ne gerektiğini söyle. Bugünün tarihi: {bugun}.\n\n'
         'SORU: {soru}\n\nÜYELER:\n{uyeler}')

_lock = threading.RLock()
_SON = {'t': 0, 'ozet': ''}
HATA_ATLA = ('404', 'not found', 'not_found', 'no longer', 'does not exist', 'model_not_found', 'decommissioned', 'unavailable', 'unsupported')


class KonseyHatasi(Exception):
    def __init__(self, kod, metin):
        super().__init__(f'{kod}: {metin}')
        self.kod, self.metin = kod, metin


# --------------------------------------------------------------------------- anahtar / ayar
def _ek():
    from . import ek
    return ek


def _ekstra_liste() -> list[dict]:
    try:
        return [e for e in (_ek().ayar('konsey_ekstra', []) or []) if isinstance(e, dict) and e.get('id') and e.get('model')]
    except Exception:
        return []


def _ekstra(id_: str) -> dict | None:
    for e in _ekstra_liste():
        if e['id'] == id_:
            return e
    return None


def anahtar(id_: str) -> str:
    if id_.startswith('x-'):
        e = _ekstra(id_)
        return anahtar(e.get('saglayici', 'openrouter')) if e else ''
    try:
        return settings.get_secret('konsey_' + id_) or ''
    except Exception:
        return ''


def anahtar_kaydet(id_: str, deger: str) -> str:
    deger = (deger or '').strip()
    if id_ not in SAGLAYICILAR and id_ != OZEL:
        return 'Hata: bilinmeyen sağlayıcı.'
    if deger and (len(deger) < 8 or ' ' in deger):
        return 'Hata: anahtar geçersiz görünüyor.'
    try:
        yer = settings.set_secret('konsey_' + id_, deger)
    except Exception as exc:
        return f'Hata: anahtar saklanamadı ({type(exc).__name__}).'
    ek = _ek()
    kapali = [x for x in (ek.ayar('konsey_kapali', []) or []) if x != id_]
    ek.ayar_yaz('konsey_kapali', kapali)
    _durum_yaz()
    if not deger:
        return 'Anahtar silindi.'
    return 'Anahtar kaydedildi' + (' (Windows Kimlik Bilgisi Yöneticisi).' if yer == 'keyring' else ' (ayar dosyası; keyring yok).')


def ozel_kaydet(url: str, model: str, ad: str = '') -> str:
    url = (url or '').strip().rstrip('/')
    model = (model or '').strip()
    if not re.match(r'^https://[^\s/]+(/\S*)?$', url):
        return 'Hata: adres https:// ile başlamalı (OpenAI uyumlu taban adres, ör. https://api.example.com/v1).'
    if not model:
        return 'Hata: model adı gerekli.'
    _ek().ayar_yaz('konsey_ozel', {'url': url, 'model': model, 'ad': (ad or 'Özel').strip()[:24]})
    _durum_yaz()
    return 'Özel sağlayıcı kaydedildi. Anahtarını da gir.'


_OR_SLUG = re.compile(r'^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*(:[a-z0-9._-]+)?$')


def slug_coz(girdi: str) -> str:
    """OpenRouter model bağlantısından (ya da doğrudan yazılmış adından) 'yazar/model:varyant' adını çıkarır."""
    s = (girdi or '').strip()
    s = re.sub(r'^https?://(www\.)?openrouter\.ai/', '', s, flags=re.I)
    s = re.split(r'[?#]', s, 1)[0].strip().strip('/')
    s = re.sub(r'^models/', '', s)
    parca = s.split('/')
    if len(parca) >= 2:
        s = parca[0] + '/' + parca[1]
    s = s.lower()
    return s if _OR_SLUG.match(s) else ''


def _or_model_bilgisi(slug: str):
    """(bulundu, bilgi|None, ulasildi). OpenRouter'ın herkese açık model listesi; anahtar gerekmez."""
    try:
        import requests
        r = requests.get('https://openrouter.ai/api/v1/models', timeout=12)
        if r.status_code >= 400:
            return False, None, False
        for m in r.json().get('data') or []:
            if isinstance(m, dict) and m.get('id') == slug:
                return True, m, True
        return False, None, True
    except Exception:
        return False, None, False


def model_ekle(girdi: str, ad: str = '') -> str:
    """HUD › KONSEY › MODEL EKLE: bir OpenRouter ÜCRETSİZ metin modelini konseye üye yapar (aynı OpenRouter anahtarı kullanılır)."""
    slug = slug_coz(girdi)
    if not slug:
        return 'Hata: model bağlantısı/adı anlaşılmadı. Örnek: https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free'
    if not slug.endswith(':free'):
        return 'Hata: yalnızca ücretsiz (:free) modeller eklenir; ücretli model sessizce para harcamasın diye reddedildi.'
    if any(e['model'] == slug for e in _ekstra_liste()):
        return 'Bu model zaten ekli.'
    if len(_ekstra_liste()) >= 6:
        return 'Hata: en fazla 6 ek model. Birini kaldır.'
    bulundu, bilgi, ulasildi = _or_model_bilgisi(slug)
    not_ = ''
    if ulasildi and not bulundu:
        return ('Hata: bu ad OpenRouter metin modelleri listesinde yok. Ses (TTS), görüntü ya da video üreten modeller konseye katılamaz '
                '(konsey yazıyla düşünür); ad yanlış olabilir ya da model kaldırılmış olabilir.')
    if bilgi:
        mimari = bilgi.get('architecture') or {}
        if 'text' not in (mimari.get('output_modalities') or ['text']):
            return 'Hata: bu model metin üretmiyor; konseye eklenemez.'
        fiyat = bilgi.get('pricing') or {}
        try:
            if float(fiyat.get('prompt') or 0) or float(fiyat.get('completion') or 0):
                return 'Hata: bu model ücretsiz görünmüyor.'
        except (TypeError, ValueError):
            pass
        ad = ad or re.sub(r'\s*\(free\)\s*$', '', str(bilgi.get('name') or '').split(': ', 1)[-1])
        if 'image' in (mimari.get('input_modalities') or []):
            not_ = 'Görsel de anlar. '
    else:
        not_ = 'Liste doğrulanamadı (bağlantı yok); TEST ile dene. '
    ad = (ad or slug.split('/')[1].split(':')[0]).strip()[:28]
    ek = _ek()
    liste = _ekstra_liste()
    n = 1 + max([int(re.sub(r'\D', '', e['id']) or 0) for e in liste] or [0])
    liste.append({'id': f'x-{n}', 'ad': ad, 'saglayici': 'openrouter', 'model': slug, 'not': not_})
    ek.ayar_yaz('konsey_ekstra', liste)
    _durum_yaz()
    return f'{ad} eklendi. ' + ('' if anahtar('openrouter') else 'Çalışması için OpenRouter anahtarını da gir (aşağıdaki OpenRouter satırı). ') + 'Bu ücretsiz modeller isteminin kaydedilmesine izin verebilir; gizli bilgi sorma.'


def model_sil(id_: str) -> str:
    ek = _ek()
    liste = [e for e in _ekstra_liste() if e['id'] != id_]
    if len(liste) == len(_ekstra_liste()):
        return 'Hata: böyle bir model yok.'
    ek.ayar_yaz('konsey_ekstra', liste)
    ek.ayar_yaz('konsey_kapali', [x for x in (ek.ayar('konsey_kapali', []) or []) if x != id_])
    _durum_yaz()
    return 'Kaldırıldı.'


def acik_mi(id_: str) -> bool:
    return id_ not in (_ek().ayar('konsey_kapali', []) or [])


def ac_kapat(id_: str, on: bool) -> str:
    ek = _ek()
    kapali = [x for x in (ek.ayar('konsey_kapali', []) or []) if x != id_]
    if not on:
        kapali.append(id_)
    ek.ayar_yaz('konsey_kapali', kapali)
    _durum_yaz()
    return 'Açıldı.' if on else 'Kapatıldı.'


def saglayici(id_: str) -> dict | None:
    if id_ == OZEL:
        o = _ek().ayar('konsey_ozel') or {}
        if not o.get('url'):
            return None
        return {'ad': o.get('ad') or 'Özel', 'url': o['url'], 'modeller': (o.get('model'),), 'anahtar_url': '', 'not': 'Kendi eklediğin servis.'}
    if id_.startswith('x-'):
        e = _ekstra(id_)
        if not e:
            return None
        b = SAGLAYICILAR.get(e.get('saglayici', 'openrouter')) or SAGLAYICILAR['openrouter']
        return {'ad': e.get('ad') or e['model'], 'url': b['url'], 'modeller': (e['model'],), 'anahtar_url': b['anahtar_url'],
                'not': (e.get('not') or '') + 'Senin eklediğin model (OpenRouter anahtarını kullanır).'}
    return SAGLAYICILAR.get(id_)


def etkin_harici() -> list[str]:
    """Anahtarı girilmiş ve açık harici sağlayıcılar."""
    out = []
    for i in (*SAGLAYICILAR, OZEL, *[e['id'] for e in _ekstra_liste()]):
        if saglayici(i) and anahtar(i) and acik_mi(i):
            out.append(i)
    return out


def gemini_var() -> bool:
    try:
        return bool(settings.get_secret('gemini'))
    except Exception:
        return False


def durum() -> dict:
    ek = _ek()
    sag = []
    for i in (*SAGLAYICILAR, OZEL, *[e['id'] for e in _ekstra_liste()]):
        s = saglayici(i)
        if s is None:
            sag.append({'id': i, 'ad': 'Özel (OpenAI uyumlu)', 'var': False, 'acik': True, 'model': '', 'url': '', 'not': 'Kendi servisini ekle: adres + model + anahtar.', 'ozel': True})
            continue
        sag.append({'id': i, 'ad': s['ad'], 'var': bool(anahtar(i)), 'acik': acik_mi(i), 'model': str(ek.ayar('konsey_model_' + i, '') or ''),
                    'url': s.get('anahtar_url', ''), 'not': s.get('not', ''), 'ozel': i == OZEL,
                    **({'ekstra': True, 'model': s['modeller'][0]} if i.startswith('x-') else {})})
    with _lock:
        son = dict(_SON)
    return {'gemini': gemini_var(), 'saglayicilar': sag, 'son': son,
            'uye_sayisi': len(etkin_harici()) + (3 if gemini_var() else 0)}


def _durum_yaz() -> None:
    try:
        _ek()._hud_durum()
    except Exception:
        pass


# --------------------------------------------------------------------------- üyeler
def _json(raw: str):
    raw = re.sub(r'<think>.*?</think>', '', raw or '', flags=re.S).strip()
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r'\{.*\}', raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return None


def _etiket(s: str) -> str:
    return re.sub(r'[^a-z0-9ğüşıöç]+', '', str(s or '').casefold().replace('İ', 'i'))


def _modelleri_listele(id_: str, s: dict, key: str) -> list[str]:
    import requests
    r = requests.get(s['url'] + '/models', headers={'Authorization': 'Bearer ' + key}, timeout=12)
    if r.status_code >= 400:
        raise KonseyHatasi(r.status_code, r.text[:160])
    ids = [str(m.get('id')) for m in (r.json().get('data') or []) if isinstance(m, dict) and m.get('id')]
    return ids


def _model_adaylari(id_: str, s: dict, key: str) -> list[str]:
    ek = _ek()
    out = []
    hatirlanan = str(ek.ayar('konsey_model_' + id_, '') or '')
    if hatirlanan:
        out.append(hatirlanan)
    if id_ == OZEL or id_.startswith('x-'):
        return [m for m in s['modeller'] if m][:1] or out
    tercih = list(s['modeller'])
    try:
        mevcut = _modelleri_listele(id_, s, key)
    except Exception as exc:
        log('ek_konsey: model listesi alınamadı', id_, type(exc).__name__)
        mevcut = []
    if mevcut:
        if s.get('ucretsiz_son_ek'):
            ucretsiz = [m for m in mevcut if m.endswith(s['ucretsiz_son_ek'])]
            guclu = [m for m in ucretsiz if re.search(r'gpt-oss|llama|qwen|gemma|nemotron|mistral|deepseek', m)]
            sirali = [m for m in tercih if m in mevcut] + guclu + [m for m in ucretsiz if m not in guclu]
        else:
            sirali = [m for m in tercih if m in mevcut]
            if not sirali:
                sirali = [m for m in mevcut if not re.search(r'whisper|embed|tts|guard|moderation|vision|ocr|image', m)][:3]
        out += [m for m in sirali if m not in out]
    else:
        out += [m for m in tercih if m not in out]
    return out[:4]


def _sohbet(s: dict, key: str, model: str, sistem: str, kullanici: str, sicaklik: float, timeout: float = 45.0) -> str:
    import requests
    govde = {'model': model, 'temperature': sicaklik, 'max_tokens': 900,
             'messages': [{'role': 'system', 'content': sistem}, {'role': 'user', 'content': kullanici}]}
    if 'openrouter.ai' in s['url']:       # düşünen modeller bütün jetonu iç düşünceye harcayıp boş cevap vermesin
        govde['max_tokens'] = 1500
        govde['reasoning'] = {'effort': 'low'}
    r = requests.post(s['url'] + '/chat/completions', headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                      json=govde, timeout=timeout)
    if r.status_code >= 400:
        raise KonseyHatasi(r.status_code, r.text[:200])
    try:
        return str(r.json()['choices'][0]['message']['content'] or '')
    except Exception:
        raise KonseyHatasi('yanıt', 'beklenmeyen yanıt biçimi')


def _harici_cagir(id_: str, sistem: str, kullanici: str, sicaklik: float) -> str:
    s = saglayici(id_)
    key = anahtar(id_)
    son = None
    for model in _model_adaylari(id_, s, key):
        try:
            cevap = _sohbet(s, key, model, sistem, kullanici, sicaklik)
            if id_ != OZEL and not id_.startswith('x-'):
                _ek().ayar_yaz('konsey_model_' + id_, model)
            return cevap
        except KonseyHatasi as exc:
            son = exc
            if exc.kod in (401, 403):
                raise
            if exc.kod == 429 or any(k in exc.metin.lower() for k in HATA_ATLA) or exc.kod in (400, 404, 422):
                continue
            raise
    raise son or KonseyHatasi('model', 'kullanılabilir model bulunamadı')


def _gemini_cagir(sistem: str, kullanici: str, sicaklik: float) -> str:
    from google import genai
    from google.genai import types
    from . import ek_model
    key = settings.get_secret('gemini')
    if not key:
        raise KonseyHatasi('anahtar', 'Gemini API anahtarı yok')
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=45000))
    cfg = types.GenerateContentConfig(system_instruction=sistem, temperature=sicaklik, response_mime_type='application/json')
    resp = ek_model.uret(client, kullanici, cfg, 'ek_konsey_model', '')
    return (getattr(resp, 'text', None) or '').strip()


class Uye:
    def __init__(self, kimlik: str, saglayici_id: str, rol: str):
        self.kimlik, self.sid, self.rol = kimlik, saglayici_id, rol
        self.ad = ROLLER[rol][0]
        self.kaynak = 'Gemini' if saglayici_id == 'gemini' else (saglayici(saglayici_id) or {}).get('ad', saglayici_id)
        self.gorus: dict | None = None
        self.hata = ''
        self.iptal = False

    def etiket(self) -> str:
        return f'{self.ad} ({self.kaynak})'

    def sor(self, kullanici: str, sicaklik: float = 0.4) -> dict | None:
        sistem = ROLLER[self.rol][1] + ' ' + ORTAK.format(bugun=dt.datetime.now().strftime('%d.%m.%Y'))
        try:
            ham = _gemini_cagir(sistem, kullanici, sicaklik) if self.sid == 'gemini' else _harici_cagir(self.sid, sistem, kullanici, sicaklik)
        except Exception as exc:
            self.hata = _hata_metni(exc)
            return None
        d = _json(ham)
        if not isinstance(d, dict) or not (d.get('oneri') or d.get('sonuc')):
            self.hata = 'yanıt çözümlenemedi'
            return None
        try:
            guven = max(0, min(100, int(float(d.get('guven', 50)))))
        except (TypeError, ValueError):
            guven = 50
        return {'oneri': ' '.join(str(d.get('oneri') or d.get('sonuc')).split())[:400], 'gerekce': ' '.join(str(d.get('gerekce') or '').split())[:600],
                'guven': guven, 'risk': ' '.join(str(d.get('risk') or '').split())[:200], 'secenek': ' '.join(str(d.get('secenek') or '').split())[:40],
                'bilmiyorum': bool(d.get('bilmiyorum')), 'degisti': bool(d.get('degisti')), 'neden': ' '.join(str(d.get('neden') or '').split())[:200]}


def _hata_metni(exc: Exception) -> str:
    if isinstance(exc, KonseyHatasi):
        if exc.kod in (401, 403):
            return 'anahtar geçersiz ya da erişim yok'
        if exc.kod == 429:
            return 'kota doldu'
        return f'hata {exc.kod}'
    s = str(exc).lower()
    if '429' in s or 'resource_exhausted' in s or 'quota' in s:
        return 'kota doldu'
    if 'timeout' in s or 'timed out' in s:
        return 'zaman aşımı'
    return type(exc).__name__


def uyeleri_kur() -> list[Uye]:
    harici = etkin_harici()[:5]
    uyeler: list[Uye] = []
    for i, sid in enumerate(harici):
        uyeler.append(Uye(f'{sid}-{i}', sid, ROL_SIRASI[i % 3]))
    if gemini_var():
        kalan = [r for r in ROL_SIRASI if r not in {u.rol for u in uyeler}] or list(ROL_SIRASI)
        n = max(1, 3 - len(harici))
        for k in range(n):
            uyeler.append(Uye(f'gemini-{k}', 'gemini', kalan[k % len(kalan)]))
    return uyeler


# --------------------------------------------------------------------------- konsey
def _paralel(uyeler: list[Uye], fn, zaman: float = 70.0) -> None:
    """Üyeleri eşzamanlı çalıştırır; `zaman` dolunca yavaş kalanları BEKLEMEDEN bırakır (eskiden `with` bloğu hepsini bekliyordu)."""
    ex = cf.ThreadPoolExecutor(max_workers=max(1, len(uyeler)), thread_name_prefix='ek-konsey')
    fut = {ex.submit(fn, u): u for u in uyeler}
    try:
        for f in cf.as_completed(fut, timeout=zaman):
            try:
                f.result()
            except Exception as exc:
                fut[f].hata = _hata_metni(exc)
    except cf.TimeoutError:
        for f, u in fut.items():
            if not f.done():
                u.iptal = True
                if not u.hata:
                    u.hata = 'zaman aşımı'
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def ayrisiyor_mu(gorusler: list[dict]) -> bool:
    if len(gorusler) < 2:
        return False
    etiketler = {_etiket(g['secenek']) for g in gorusler if g['secenek']}
    if len(etiketler) > 1:
        return True
    if any(g['bilmiyorum'] for g in gorusler):
        return True
    gv = [g['guven'] for g in gorusler]
    return len(gv) > 1 and statistics.pstdev(gv) > 22


def oy_say(uyeler: list[Uye]) -> dict:
    """Seçenek etiketine göre oylar (kodla). {'oylar': {etiket: n}, 'agirlikli': {etiket: toplam güven}, 'kazanan': etiket|None, 'beraberlik': bool}"""
    oy, ag, ad = {}, {}, {}
    for u in uyeler:
        g = u.gorus
        if not g or not g['secenek']:
            continue
        k = _etiket(g['secenek'])
        if not k:
            continue
        oy[k] = oy.get(k, 0) + 1
        ag[k] = ag.get(k, 0) + g['guven']
        ad.setdefault(k, g['secenek'])
    if not oy:
        return {'oylar': {}, 'agirlikli': {}, 'kazanan': None, 'beraberlik': False}
    sirali = sorted(oy, key=lambda k: (oy[k], ag[k]), reverse=True)
    ber = len(sirali) > 1 and oy[sirali[0]] == oy[sirali[1]] and ag[sirali[0]] == ag[sirali[1]]
    return {'oylar': {ad[k]: oy[k] for k in sirali}, 'agirlikli': {ad[k]: ag[k] for k in sirali}, 'kazanan': ad[sirali[0]], 'beraberlik': ber}


def _uyeler_metni(uyeler: list[Uye], kendi: Uye | None = None) -> str:
    out = []
    for i, u in enumerate(uyeler, 1):
        g = u.gorus
        if not g or u is kendi:
            continue
        out.append(f"Üye {i} — {u.ad}: {g['oneri']} | Gerekçe: {g['gerekce'] or '-'} | Güven: {g['guven']} | Risk: {g['risk'] or '-'}"
                   + (f" | Seçenek: {g['secenek']}" if g['secenek'] else '') + (' | BİLMİYORUM' if g['bilmiyorum'] else ''))
    return '\n'.join(out)


def _hakem_cagir(soru: str, uyeler: list[Uye]) -> dict | None:
    istem = HAKEM.format(bugun=dt.datetime.now().strftime('%d.%m.%Y'), soru=soru, uyeler=_uyeler_metni(uyeler))
    sistem = 'Tarafsız, titiz bir hakemsin. Yalnızca JSON döndür.'
    try:
        if gemini_var():
            ham = _gemini_cagir(sistem, istem, 0.2)
        else:
            sid = next(iter(etkin_harici()), None)
            if not sid:
                return None
            ham = _harici_cagir(sid, sistem, istem, 0.2)
    except Exception as exc:
        log('ek_konsey: hakem çağrısı başarısız', _hata_metni(exc))
        return None
    d = _json(ham)
    if not isinstance(d, dict) or not d.get('sonuc'):
        return None
    try:
        g = max(0, min(100, int(float(d.get('guven', 50)))))
    except (TypeError, ValueError):
        g = 50
    f = lambda k, n=500: ' '.join(str(d.get(k) or '').split())[:n]  # noqa: E731
    return {'sonuc': f('sonuc'), 'neden': f('neden'), 'karsi_gorus': f('karsi_gorus'), 'dogrulanacak': f('dogrulanacak', 300), 'guven': g, 'sonraki_adim': f('sonraki_adim', 300)}


def konsey(soru: str, baglam: str = '', derin: bool = False) -> str:
    soru = ' '.join(str(soru or '').split())
    if len(soru) < 6:
        return 'Hata: konseye danışılacak soru boş ya da çok kısa.'
    uyeler = uyeleri_kur()
    if not uyeler:
        return ('Hata: konsey kurulamadı — Gemini API anahtarı ya da en az bir ücretsiz sağlayıcı anahtarı gerekli '
                '(BLOOM › PANEL › KONSEY).')
    baglam = ' '.join(str(baglam or '').split())[:1500]
    t0 = time.time()
    from . import ek_ogren
    ek_ogren.bildir('KONSEY TOPLANIYOR · ' + ', '.join(sorted({u.kaynak for u in uyeler})) + f' · {len(uyeler)} üye')
    soru_metni = f'SORU: {soru}' + (f'\nBAĞLAM: {baglam}' if baglam else '')
    # --- tur 1: bağımsız görüş
    def t1(u: Uye):
        g = u.sor(soru_metni, 0.35 if u.rol != 'supheci' else 0.5)
        if not u.iptal:
            u.gorus = g
    _paralel(uyeler, t1, TUR1_SN)
    aktif = [u for u in uyeler if u.gorus]
    if not aktif:
        hatalar = '; '.join(f'{u.kaynak}: {u.hata}' for u in uyeler)
        return f'Hata: hiçbir üye cevap veremedi ({hatalar}). İnternet bağlantısını, anahtarları ve kotaları kontrol et.'
    tur = 1
    # --- tur 2: ayrışma varsa karşılıklı sorgulama
    if len(aktif) >= 2 and (derin or ayrisiyor_mu([u.gorus for u in aktif])):
        tur = 2
        ilk = {u.kimlik: dict(u.gorus) for u in aktif}

        def t2(u: Uye):
            yeni = u.sor(soru_metni + TUR2.format(digerleri=_uyeler_metni(aktif, kendi=u)), 0.3)
            if yeni and not u.iptal:
                u.gorus = yeni
        _paralel(aktif, t2, TUR2_SN)
        for u in aktif:
            if u.gorus and ilk.get(u.kimlik) and _etiket(u.gorus['secenek']) != _etiket(ilk[u.kimlik]['secenek']):
                u.gorus['degisti'] = True
    sayim = oy_say(aktif)
    hakem = _hakem_cagir(soru, aktif) if len(aktif) >= 1 else None
    sonuc = _bicimle(soru, uyeler, aktif, tur, sayim, hakem, time.time() - t0)
    with _lock:
        _SON.update(t=int(time.time()), ozet=(hakem['sonuc'] if hakem else aktif[0].gorus['oneri'])[:200])
    _durum_yaz()
    return sonuc


def _bicimle(soru, uyeler, aktif, tur, sayim, hakem, sure) -> str:
    gv = [u.gorus['guven'] for u in aktif]
    ort = round(sum(gv) / len(gv))
    kaynaklar = sorted({u.kaynak for u in aktif})
    ayni_model = len(kaynaklar) == 1
    satirlar = [f"KONSEY SONUCU — {len(aktif)}/{len(uyeler)} üye cevap verdi ({', '.join(kaynaklar)}), {tur} tur, {sure:.0f} sn"]
    if hakem:
        satirlar.append('Karar: ' + hakem['sonuc'])
        if hakem['neden']:
            satirlar.append('Gerekçe: ' + hakem['neden'])
        if hakem['karsi_gorus']:
            satirlar.append('Karşı görüş: ' + hakem['karsi_gorus'])
        if hakem['dogrulanacak']:
            satirlar.append('Doğrulanması gereken: ' + hakem['dogrulanacak'])
        if hakem['sonraki_adim']:
            satirlar.append('Önerilen adım: ' + hakem['sonraki_adim'])
        satirlar.append(f"Güven: hakem %{hakem['guven']}, üyelerin ortalaması %{ort}")
    else:
        en = max(aktif, key=lambda u: u.gorus['guven'])
        satirlar.append('Karar (hakem çalışmadı; en yüksek güvenli üyenin görüşü): ' + en.gorus['oneri'])
        satirlar.append(f'Güven: üyelerin ortalaması %{ort}')
    if sayim['oylar']:
        satirlar.append('Oylar (kodla sayıldı): ' + ', '.join(f'{k}: {n}' for k, n in sayim['oylar'].items())
                        + (' — BERABERE' if sayim['beraberlik'] else ''))
    degisen = [u.etiket() for u in aktif if u.gorus.get('degisti')]
    if degisen:
        satirlar.append('Görüşünü değiştirenler: ' + ', '.join(degisen))
    satirlar.append('Üyelerin son görüşleri:')
    for u in aktif:
        g = u.gorus
        satirlar.append(f"- {u.etiket()}: {g['oneri']} [güven %{g['guven']}]" + (f" Risk: {g['risk']}" if g['risk'] else '') + (' (bilmiyorum diyor)' if g['bilmiyorum'] else ''))
    atlanan = [f'{u.kaynak}/{u.ad}: {u.hata}' for u in uyeler if not u.gorus]
    if atlanan:
        satirlar.append('Cevap vermeyenler: ' + '; '.join(atlanan))
    if ayni_model:
        satirlar.append('UYARI: tüm üyeler aynı modelin (Gemini) farklı ROLLERİ; gerçek model çeşitliliği yok. Başka bir ücretsiz sağlayıcı anahtarı eklenirse çeşitlilik artar.')
    satirlar.append('(Modele not: bunlar başka yapay zekâların görüşleridir, kesin doğru değildir. Kullanıcıya kararı gerekçesiyle, karşı görüşü de saklamadan, kısa anlat; '
                    'olgusal iddiaları gerekirse web_search/arastir ile doğrula.)')
    return '\n'.join(satirlar)


# --------------------------------------------------------------------------- sınama / araç
def dene(id_: str) -> str:
    """Bir sağlayıcıyı tek kısa istekle sınar (HUD › TEST)."""
    if id_ == 'gemini':
        try:
            _gemini_cagir('Yalnızca JSON döndür.', 'Şunu döndür: {"oneri": "tamam", "guven": 100}', 0.0)
            return 'Gemini çalışıyor.'
        except Exception as exc:
            return 'Hata: Gemini — ' + _hata_metni(exc)
    s = saglayici(id_)
    if not s:
        return 'Hata: bilinmeyen sağlayıcı.'
    if not anahtar(id_):
        return 'Hata: önce anahtarı kaydet.'
    try:
        ham = _harici_cagir(id_, 'Yalnızca JSON döndür.', 'Şunu döndür: {"oneri": "tamam", "guven": 100}', 0.0)
    except Exception as exc:
        return f"Hata: {s['ad']} — " + _hata_metni(exc)
    model = _ek().ayar('konsey_model_' + id_, '')
    return f"{s['ad']} çalışıyor" + (f' (model: {model}).' if model else '.') if ham else f"Hata: {s['ad']} boş yanıt verdi."


_ARKA = {'calisan': False}
_ARKA_KILIT = threading.Lock()


def arac_konsey(a, _c=None) -> str:
    """Model aracı. En çok KONSEY_BEKLE sn bekler; konsey bitmediyse arka planda sürer ve bitince asistana duyurulur
    (uygulamanın araç sınırı 30 sn: aşılırsa araç 'yarıda bırakıldı' sayılır ve sonuç kaybolurdu)."""
    a = a or {}
    soru, baglam, derin = str(a.get('soru') or ''), str(a.get('baglam') or ''), bool(a.get('derin'))
    with _ARKA_KILIT:
        if _ARKA['calisan']:
            return 'Konsey zaten toplanıyor; bitince sonucu söyleyeceğim. Kullanıcıya tek cümleyle bunu söyle.'
        _ARKA['calisan'] = True
    bitti = threading.Event()
    durum = {'bitti': False, 'cikti': '', 'arka': False}
    kilit = threading.Lock()

    def is_():
        try:
            cikti = konsey(soru, baglam, derin)
        except Exception as exc:
            log('ek_konsey: hata', type(exc).__name__, exc)
            cikti = f'Hata: konsey çalışamadı ({type(exc).__name__}).'
        with _ARKA_KILIT:
            _ARKA['calisan'] = False
        with kilit:
            durum['bitti'], durum['cikti'] = True, cikti
            arka = durum['arka']
        bitti.set()
        if arka:
            try:
                from . import ek_ogren
                ek_ogren.bildir('KONSEY TAMAMLANDI' if not cikti.startswith('Hata') else 'KONSEY ÇALIŞMADI')
                __import__(__package__ + '.ek_isler', fromlist=['x']).teslim_et('konsey', '[KONSEY BİTTİ] Kullanıcının daha önce istediği konsey danışması tamamlandı. ' + cikti)
            except Exception as exc:
                log('ek_konsey: duyuru yapılamadı', type(exc).__name__)

    threading.Thread(target=is_, daemon=True, name='ek-konsey-ana').start()
    bitti.wait(KONSEY_BEKLE)
    with kilit:
        if durum['bitti']:
            return durum['cikti']
        durum['arka'] = True
    return ('Konsey hâlâ toplanıyor (üyeler yavaş yanıtlıyor; araç süresi dolmasın diye arka plana alındı). Bitince sonucu ben sana söyleyeceğim; '
            'kaybolmaz. Kullanıcıya bunu tek cümleyle söyle; beklerken başka işe devam edebilir.')
