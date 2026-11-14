"""BLOOM EK — Spotify liste/kitaplık yönetimi (Spotify Web API, PKCE ile giriş).

V4'ün mevcut Spotify açma/çalma işi (spotify_cli.exe) olduğu gibi kalır. Bu modül yalnızca KULLANICI İSTEYİNCE
çalma listelerine şarkı ekler/çıkarır, liste oluşturur, beğenir ve son işlemi geri alır.

İlke: hiçbir şey kendiliğinden yapılmaz. Araç yalnızca kullanıcı açıkça isteyince çağrılır; emin olunamayan
eşleşmede (belirsiz liste ya da şarkı) işlem YAPILMAZ, adaylar sunulur. Yapılan her değişiklik
`ek/spotify-islemler.jsonl` dosyasına yazılır ve geri alınabilir.

Kurulum (bir kez): kullanıcı developer.spotify.com'da bir uygulama oluşturur, Redirect URI olarak
REDIRECT_URI'yi ekler, Client ID'yi HUD'a yapıştırır. Client secret gerekmez (PKCE). Spotify (2026) geliştirme
modundaki uygulamanın sahibinden aktif Premium ister.
"""

from __future__ import annotations
import base64
import difflib
import hashlib
import http.server
import json
import secrets
import threading
import time
import unicodedata
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse
from . import settings
from .log import log

API = 'https://api.spotify.com/v1'
HESAPLAR = 'https://accounts.spotify.com'
PORT = 47835
REDIRECT_URI = f'http://127.0.0.1:{PORT}/callback'
KAPSAM = ('playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public '
          'user-library-read user-library-modify user-read-currently-playing user-read-playback-state')
SECRET = 'spotify_refresh'
BEKLEME_SN = 240
ISLEM_DOSYASI = 'spotify-islemler.jsonl'
MAKS_OGE = 600

_lock = threading.RLock()
_tok = {'access': '', 'bitis': 0.0}
_login = {'durum': '', 'mesaj': ''}       # '' | 'bekliyor' | 'tamam' | 'hata'
_yol = {'items': True}                     # liste öğeleri uç noktası: /items (2026) — 404 olursa /tracks


class SpotifyHata(Exception):
    def __init__(self, kod: int, mesaj: str):
        super().__init__(mesaj)
        self.kod = kod
        self.mesaj = mesaj


# --------------------------------------------------------------------------- küçük yardımcılar
def _ek():
    from . import ek
    return ek


def _norm(t: str) -> str:
    t = unicodedata.normalize('NFKD', (t or '').strip().casefold().replace('ı', 'i'))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in t).split())


_STOP = {'the', 'a', 'an', 've', 'ile', 'by', 'feat', 'ft', 'sarkisi', 'sarki', 'adli', 'adlı', 'of'}


def _toks(t: str) -> list[str]:
    return [w for w in _norm(t).split() if w not in _STOP]


def _kapsam(sorgu: str, metin: str) -> float:
    """Sorgudaki sözcüklerin ne kadarı metinde var (0-1)."""
    q = _toks(sorgu)
    if not q:
        return 0.0
    words = set(_toks(metin))
    hit = 0
    for w in q:
        if w in words or any(len(w) >= 4 and (x.startswith(w[:4]) and abs(len(x) - len(w)) <= 2) for x in words):
            hit += 1
    return hit / len(q)


def _client_id() -> str:
    return str(_ek().ayar('spotify_client_id', '') or '').strip()


def baglanti_durumu() -> dict:
    ek = _ek()
    return {'client_id': bool(_client_id()), 'bagli': bool(settings.get_secret(SECRET)),
            'hesap': str(ek.ayar('spotify_hesap', '') or ''), 'premium': ek.ayar('spotify_premium', None),
            'login': _login['durum'], 'mesaj': _login['mesaj'], 'redirect': REDIRECT_URI}


def _bildir() -> None:
    try:
        _ek()._hud_durum()
    except Exception:
        pass


# --------------------------------------------------------------------------- giriş (PKCE)
def _http():
    import requests
    return requests


def _kod_degistir(data: dict) -> dict:
    r = _http().post(HESAPLAR + '/api/token', data=data, timeout=15)
    try:
        js = r.json()
    except ValueError:
        js = {}
    if r.status_code != 200 or 'access_token' not in js:
        raise SpotifyHata(r.status_code, str(js.get('error_description') or js.get('error') or r.text[:120]))
    return js


def _jeton_kaydet(js: dict) -> None:
    with _lock:
        _tok['access'] = js['access_token']
        _tok['bitis'] = time.time() + float(js.get('expires_in', 3600)) - 60
        if js.get('refresh_token'):
            settings.set_secret(SECRET, js['refresh_token'])


def _erisim() -> str:
    with _lock:
        if _tok['access'] and time.time() < _tok['bitis']:
            return _tok['access']
        refresh = settings.get_secret(SECRET)
        cid = _client_id()
        if not refresh or not cid:
            raise SpotifyHata(0, 'Spotify bağlı değil. HUD\'da ODAK › SPOTIFY bölümünden bir kez bağla.')
        try:
            js = _kod_degistir({'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': cid})
        except SpotifyHata as e:
            if e.kod in (400, 401):
                settings.set_secret(SECRET, '')
                _tok['access'] = ''
                _bildir()
                raise SpotifyHata(0, 'Spotify oturumu geçersiz oldu; ODAK › SPOTIFY\'dan yeniden bağla.')
            raise
        _jeton_kaydet(js)
        return _tok['access']


def kimlik_kaydet(client_id: str) -> str:
    cid = ''.join((client_id or '').split())
    if len(cid) < 20 or not all(c.isalnum() for c in cid):
        return 'Hata: Client ID 32 karakterlik harf-rakam dizisidir; Spotify panelinden kopyala.'
    _ek().ayar_yaz('spotify_client_id', cid)
    _bildir()
    return 'Client ID kaydedildi.'


def baglan() -> str:
    """Tarayıcıda Spotify iznini açar; 127.0.0.1'e dönen kodu yakalar. Hemen döner, sonuç HUD durumuna yazılır."""
    cid = _client_id()
    if not cid:
        return 'Hata: önce Client ID gerekli (ODAK › SPOTIFY).'
    if _login['durum'] == 'bekliyor':
        return 'Bağlantı penceresi zaten açık; tarayıcıda Spotify iznini onayla.'
    verifier = secrets.token_urlsafe(72)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(16)
    got: dict = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            if u.path != '/callback':
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(u.query)
            got['code'] = (q.get('code') or [''])[0]
            got['error'] = (q.get('error') or [''])[0]
            got['state'] = (q.get('state') or [''])[0]
            ok = bool(got['code']) and got['state'] == state
            body = ('<meta charset="utf-8"><body style="font:18px sans-serif;background:#0b1620;color:#cfe;text-align:center;'
                    'padding-top:20vh"><h2>' + ('BLOOM Spotify\'a bağlandı' if ok else 'Bağlantı olmadı') +
                    '</h2><p>Bu pencereyi kapatabilirsin.</p>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *a):
            pass

    try:
        srv = http.server.HTTPServer(('127.0.0.1', PORT), H)
    except OSError:
        _login.update(durum='hata', mesaj=f'{PORT} numaralı yerel kapı meşgul; başka bir program kullanıyor olabilir.')
        _bildir()
        return 'Hata: ' + _login['mesaj']
    srv.timeout = 1
    _login.update(durum='bekliyor', mesaj='Tarayıcıda Spotify iznini onayla…')

    def run():
        try:
            end = time.time() + BEKLEME_SN
            while not done.is_set() and time.time() < end:
                srv.handle_request()
            if not done.is_set():
                raise SpotifyHata(0, 'Süre doldu; izin verilmedi.')
            if got.get('error'):
                raise SpotifyHata(0, 'Spotify izni reddedildi (' + got['error'] + ').')
            if got.get('state') != state or not got.get('code'):
                raise SpotifyHata(0, 'Dönen yanıt doğrulanamadı.')
            js = _kod_degistir({'grant_type': 'authorization_code', 'code': got['code'], 'redirect_uri': REDIRECT_URI,
                                'client_id': cid, 'code_verifier': verifier})
            _jeton_kaydet(js)
            me = _api('GET', '/me')
            ek = _ek()
            ek.ayar_yaz('spotify_hesap', str(me.get('display_name') or me.get('id') or ''))
            ek.ayar_yaz('spotify_id', str(me.get('id') or ''))
            ek.ayar_yaz('spotify_premium', (me.get('product') == 'premium') if me.get('product') else None)
            _login.update(durum='tamam', mesaj='')
            log('ek: Spotify bağlandı')
        except SpotifyHata as e:
            _login.update(durum='hata', mesaj=e.mesaj)
            log('ek: Spotify bağlanamadı', e.mesaj)
        except Exception as exc:
            _login.update(durum='hata', mesaj=type(exc).__name__)
            log('ek: Spotify bağlanamadı', type(exc).__name__, exc)
        finally:
            try:
                srv.server_close()
            except Exception:
                pass
            _bildir()

    threading.Thread(target=run, daemon=True, name='ek-spotify-giris').start()
    url = HESAPLAR + '/authorize?' + urlencode({
        'response_type': 'code', 'client_id': cid, 'scope': KAPSAM, 'redirect_uri': REDIRECT_URI, 'state': state,
        'code_challenge_method': 'S256', 'code_challenge': challenge})
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass
    _bildir()
    return 'Tarayıcıda Spotify izin sayfası açıldı. Onaylayınca bağlantı tamamlanır.'


def kes() -> str:
    settings.set_secret(SECRET, '')
    with _lock:
        _tok.update(access='', bitis=0.0)
    ek = _ek()
    for k in ('spotify_hesap', 'spotify_id', 'spotify_premium'):
        ek.ayar_yaz(k, '' if k != 'spotify_premium' else None)
    _login.update(durum='', mesaj='')
    _bildir()
    return 'Spotify bağlantısı kaldırıldı.'


# --------------------------------------------------------------------------- API
_HATA = {
    400: 'Spotify isteği anlayamadı (400).',
    401: 'Spotify oturumu geçersiz (401).',
    403: ('Spotify bu isteği reddetti (403). Geliştirici uygulaması için hesap sahibinin aktif Spotify Premium\'u '
          'olmalı; ayrıca bu işlem için izin gerekebilir — gerekirse ODAK › SPOTIFY\'dan bağlantıyı yenile.'),
    404: 'Spotify bunu bulamadı (404).',
    429: 'Spotify şu an çok istek aldı (429); biraz sonra tekrar dene.',
}


def _api(method: str, path: str, params: dict | None = None, body: dict | None = None, _tekrar: bool = True):
    tok = _erisim()
    r = _http().request(method, API + path, params=params, json=body, timeout=15,
                        headers={'Authorization': 'Bearer ' + tok})
    if r.status_code == 401 and _tekrar:
        with _lock:
            _tok['bitis'] = 0.0
        return _api(method, path, params, body, False)
    if r.status_code == 429 and _tekrar:
        try:
            time.sleep(min(float(r.headers.get('Retry-After', 1)), 4))
        except ValueError:
            time.sleep(1)
        return _api(method, path, params, body, False)
    if r.status_code in (200, 201, 202):
        try:
            return r.json()
        except ValueError:
            return {}
    if r.status_code == 204:
        return {}
    detay = ''
    try:
        detay = str((r.json().get('error') or {}).get('message') or '')[:140]
    except Exception:
        pass
    raise SpotifyHata(r.status_code, _HATA.get(r.status_code, f'Spotify hata verdi ({r.status_code}).') +
                      (f' [{detay}]' if detay else ''))


def _ogeler_yolu(pid: str) -> str:
    return f'/playlists/{pid}/' + ('items' if _yol['items'] else 'tracks')


def _liste_api(method: str, pid: str, params=None, body=None):
    try:
        return _api(method, _ogeler_yolu(pid), params, body)
    except SpotifyHata as e:
        if e.kod in (404, 410) and _yol['items']:
            _yol['items'] = False
            return _api(method, _ogeler_yolu(pid), params, body)
        raise


# --------------------------------------------------------------------------- listeler / şarkılar
def _ben() -> str:
    me = str(_ek().ayar('spotify_id', '') or '')
    if not me:
        me = str(_api('GET', '/me').get('id') or '')
        _ek().ayar_yaz('spotify_id', me)
    return me


def listelerim() -> list[dict]:
    out, off = [], 0
    while off < 400:
        js = _api('GET', '/me/playlists', {'limit': 50, 'offset': off})
        items = js.get('items') or []
        for p in items:
            if not isinstance(p, dict) or not p.get('id'):
                continue
            tr = p.get('items') if isinstance(p.get('items'), dict) else (p.get('tracks') if isinstance(p.get('tracks'), dict) else {})
            out.append({'id': p['id'], 'ad': p.get('name') or '', 'sahip': (p.get('owner') or {}).get('id', ''),
                        'ortak': bool(p.get('collaborative')), 'adet': (tr or {}).get('total')})
        if len(items) < 50 or not js.get('next'):
            break
        off += 50
    return out


def _yazilabilir(p: dict, ben: str) -> bool:
    return p['sahip'] == ben or p['ortak']


def liste_bul(ad: str, yazilacak: bool = False) -> tuple[dict | None, str]:
    """(liste, mesaj). Belirsizse liste None ve mesaj aday sunar; asla tahminle seçmez."""
    ad = (ad or '').strip()
    if not ad:
        return None, 'Hangi çalma listesi? Adını söylemeni istemeliyim.'
    ben = _ben()
    hepsi = listelerim()
    n = _norm(ad)
    uyan = [p for p in hepsi if _norm(p['ad']) == n]
    if not uyan:
        uyan = [p for p in hepsi if n and (_norm(p['ad']).startswith(n) or n in _norm(p['ad']))]
    if not uyan:
        q = _toks(ad)
        uyan = [p for p in hepsi if q and all(_kapsam(w, p['ad']) >= 1 for w in q)]
    if not uyan:
        yakin = difflib.get_close_matches(n, [_norm(p['ad']) for p in hepsi], n=3, cutoff=0.6)
        adaylar = [p['ad'] for p in hepsi if _norm(p['ad']) in yakin]
        if adaylar:
            return None, f'"{ad}" adlı liste yok. Şunlardan biri mi: ' + '; '.join(adaylar[:3]) + '? Sormadan işlem yapmadım.'
        return None, f'"{ad}" adlı bir çalma listen yok.'
    if len(uyan) > 1:
        return None, 'Birden fazla liste uyuyor: ' + '; '.join(p['ad'] for p in uyan[:5]) + '. Hangisi? İşlem yapmadım.'
    p = uyan[0]
    if yazilacak and not _yazilabilir(p, ben):
        return None, f'"{p["ad"]}" listesi sana ait değil ya da ortak değil; Spotify buna şarkı eklemeye/çıkarmaya izin vermez.'
    return p, ''


def _oge_bilgi(it: dict) -> dict | None:
    t = it.get('item') or it.get('track') or {}
    if not isinstance(t, dict) or not t.get('uri'):
        return None
    return {'uri': t['uri'], 'ad': t.get('name') or '', 'sanatci': ', '.join(a.get('name', '') for a in (t.get('artists') or [])),
            'tur': t.get('type') or 'track'}


def liste_ogeleri(pid: str, maks: int = MAKS_OGE) -> list[dict]:
    out, off = [], 0
    while off < maks:
        js = _liste_api('GET', pid, {'limit': 50, 'offset': off})
        items = js.get('items') or []
        for it in items:
            b = _oge_bilgi(it) if isinstance(it, dict) else None
            if b:
                out.append(b)
        if len(items) < 50 or not js.get('next'):
            break
        off += 50
    return out


def _etiket(t: dict) -> str:
    return f"{t['ad']} — {t['sanatci']}" if t.get('sanatci') else t['ad']


def sarki_ara(sorgu: str) -> tuple[dict | None, list[dict]]:
    """(kesin eşleşme | None, adaylar). Kesin: sorgu sözcüklerinin ≥%75'i parça adı+sanatçıda ve en iyi tek aday."""
    sorgu = (sorgu or '').strip()
    if sorgu.startswith('spotify:track:'):
        js = _api('GET', '/tracks/' + sorgu.split(':')[-1])
        b = _oge_bilgi({'item': js})
        return (b, [b]) if b else (None, [])
    js = _api('GET', '/search', {'q': sorgu, 'type': 'track', 'limit': 8})
    tr = (js.get('tracks') or {}).get('items') or []
    adaylar = []
    for t in tr:
        b = _oge_bilgi({'item': t})
        if not b:
            continue
        b['puan'] = _kapsam(sorgu, b['ad'] + ' ' + b['sanatci'])
        b['ad_puan'] = _kapsam(b['ad'], sorgu)
        b['pop'] = t.get('popularity') or 0
        adaylar.append(b)
    adaylar.sort(key=lambda b: (-b['puan'], -b['ad_puan'], -b['pop']))
    if not adaylar or adaylar[0]['puan'] < 0.75:
        return None, adaylar[:3]
    en = adaylar[0]
    # aynı puanda FARKLI şarkılar varsa (ör. aynı adlı iki şarkı) belirsiz say; aynı şarkının sürümleri sorun değil
    ayni = [b for b in adaylar if b['puan'] >= en['puan'] - 1e-9 and b['ad_puan'] >= en['ad_puan'] - 1e-9
            and _norm(b['ad']) != _norm(en['ad'])]
    if ayni:
        return None, adaylar[:3]
    benzer = [b for b in adaylar if b['puan'] >= en['puan'] - 1e-9 and _norm(b['ad']) == _norm(en['ad'])
              and _norm(b['sanatci']) != _norm(en['sanatci'])]
    if benzer and en['ad_puan'] >= 1 and _kapsam(sorgu, en['sanatci']) == 0:
        return None, adaylar[:3]       # "Hayat" gibi adı aynı, sanatçısı belirtilmemiş: sor
    return en, adaylar[:3]


# --------------------------------------------------------------------------- işlem günlüğü ve geri alma
def _gunluk(eylem: str, liste: str, parcalar: list[dict], **ekstra) -> None:
    rec = {'t': int(time.time()), 'id': secrets.token_hex(4), 'eylem': eylem, 'liste': liste, 'parcalar': [_etiket(p) for p in parcalar], **ekstra}
    try:
        p = _ek()._dir() / ISLEM_DOSYASI
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        lines = p.read_text(encoding='utf-8').splitlines()
        if len(lines) > 300:
            p.write_text('\n'.join(lines[-200:]) + '\n', encoding='utf-8')
    except OSError:
        pass
    _bildir()


def son_islemler(n: int = 8) -> list[dict]:
    try:
        lines = (_ek()._dir() / ISLEM_DOSYASI).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


# --------------------------------------------------------------------------- eylemler
def sarki_ekle(liste_ad: str, sarkilar: list[str], liste: dict | None = None) -> str:
    sarkilar = [s for s in (str(x).strip() for x in (sarkilar or [])) if s][:10]
    if not sarkilar:
        return 'Hangi şarkıyı eklemem gerektiğini söylemedin; işlem yapmadım.'
    p, msg = (liste, '') if liste else liste_bul(liste_ad, True)
    if not p:
        return msg
    mevcut = {t['uri'] for t in liste_ogeleri(p['id'])}
    eklenecek, zaten, belirsiz = [], [], []
    for s in sarkilar:
        tam, adaylar = sarki_ara(s)
        if tam is None:
            belirsiz.append((s, adaylar))
        elif tam['uri'] in mevcut or any(tam['uri'] == e['uri'] for e in eklenecek):
            zaten.append(tam)
        else:
            eklenecek.append(tam)
    if eklenecek:
        _liste_api('POST', p['id'], body={'uris': [t['uri'] for t in eklenecek]})
        _gunluk('ekle', p['ad'], eklenecek, liste_id=p['id'], uris=[t['uri'] for t in eklenecek])
    parts = []
    if eklenecek:
        parts.append(f'"{p["ad"]}" listesine eklendi: ' + '; '.join(_etiket(t) for t in eklenecek) + '.')
    if zaten:
        parts.append('Zaten listede olduğu için eklenmedi: ' + '; '.join(_etiket(t) for t in zaten) + '.')
    for s, adaylar in belirsiz:
        if adaylar:
            parts.append(f'"{s}" için emin olamadım, EKLEMEDİM. Adaylar: ' +
                         '; '.join(f'{i}) {_etiket(a)} [{a["uri"]}]' for i, a in enumerate(adaylar, 1)) +
                         '. Kullanıcıya hangisi olduğunu sor; seçince uri ile tekrar çağır.')
        else:
            parts.append(f'"{s}" için Spotify\'da eşleşen şarkı bulamadım.')
    return ' '.join(parts)


def sarki_cikar(liste_ad: str, sarkilar: list[str]) -> str:
    sarkilar = [s for s in (str(x).strip() for x in (sarkilar or [])) if s][:10]
    if not sarkilar:
        return 'Hangi şarkıyı çıkarmam gerektiğini söylemedin; işlem yapmadım.'
    p, msg = liste_bul(liste_ad, True)
    if not p:
        return msg
    ogeler = liste_ogeleri(p['id'])
    cikar, yok, belirsiz = [], [], []
    for s in sarkilar:
        if s.startswith('spotify:track:'):
            uyan = [o for o in ogeler if o['uri'] == s]
        else:
            sk = [(o, _kapsam(s, o['ad'] + ' ' + o['sanatci'])) for o in ogeler]
            en = max((k for _, k in sk), default=0)
            uyan = [o for o, k in sk if k >= 0.75 and k >= en - 1e-9]
        uris = {o['uri'] for o in uyan}
        if not uyan:
            yok.append(s)
        elif len(uris) > 1:
            belirsiz.append((s, list({o['uri']: o for o in uyan}.values())[:4]))
        elif uyan[0]['uri'] not in {c['uri'] for c in cikar}:
            cikar.append(uyan[0])
    if cikar:
        govde = [{'uri': c['uri']} for c in cikar]
        try:
            _liste_api('DELETE', p['id'], body={'items': govde})
        except SpotifyHata as e:
            if e.kod != 400:
                raise
            _liste_api('DELETE', p['id'], body={'tracks': govde})
        _gunluk('cikar', p['ad'], cikar, liste_id=p['id'], uris=[c['uri'] for c in cikar])
    parts = []
    if cikar:
        parts.append(f'"{p["ad"]}" listesinden çıkarıldı: ' + '; '.join(_etiket(t) for t in cikar) + '.')
    if yok:
        parts.append('Listede bulamadım: ' + '; '.join(yok) + '.')
    for s, adaylar in belirsiz:
        parts.append(f'"{s}" listede birden fazla şarkıya uyuyor, ÇIKARMADIM: ' +
                     '; '.join(f'{_etiket(a)} [{a["uri"]}]' for a in adaylar) + '. Hangisi? Sor; seçince uri ile çağır.')
    return ' '.join(parts)


def liste_icerigi(liste_ad: str, n: int = 25) -> str:
    p, msg = liste_bul(liste_ad, False)
    if not p:
        return msg
    ogeler = liste_ogeleri(p['id'], 300)
    if not ogeler:
        return f'"{p["ad"]}" listesi boş (ya da içeriğini görme iznim yok).'
    gos = ogeler[:max(1, min(int(n or 25), 50))]
    return f'"{p["ad"]}" — {len(ogeler)} parça. İlkleri: ' + '; '.join(_etiket(t) for t in gos)


def listeleri_goster() -> str:
    ben = _ben()
    ls = listelerim()
    if not ls:
        return 'Çalma listen yok.'
    return f'{len(ls)} çalma listen var: ' + '; '.join(p['ad'] + ('' if _yazilabilir(p, ben) else ' (salt okunur)') for p in ls[:40])


def liste_olustur(ad: str, herkese_acik: bool = False) -> str:
    ad = ' '.join((ad or '').split())[:100]
    if not ad:
        return 'Listeye ne ad vereceğimi söylemedin; oluşturmadım.'
    js = _api('POST', '/me/playlists', body={'name': ad, 'public': bool(herkese_acik)})
    _gunluk('olustur', ad, [], liste_id=js.get('id', ''))
    return f'"{ad}" adlı ' + ('herkese açık' if herkese_acik else 'gizli') + ' çalma listesi oluşturuldu (boş).'


def calan() -> dict | None:
    js = _api('GET', '/me/player/currently-playing')
    return _oge_bilgi({'item': js.get('item')}) if js.get('item') else None


def calani_ekle(liste_ad: str) -> str:
    t = calan()
    if not t:
        return 'Şu an Spotify\'da çalan bir şey görünmüyor; işlem yapmadım.'
    p, msg = liste_bul(liste_ad, True)
    if not p:
        return msg
    return sarki_ekle('', [t['uri']], p)


def kitaplik(uri_veya_sorgu: str, ekle: bool) -> str:
    if not uri_veya_sorgu:
        return 'Hangi şarkı? İşlem yapmadım.'
    if uri_veya_sorgu in ('calan', 'şu an çalan', 'su an calan'):
        t = calan()
        adaylar = [t] if t else []
        tam = t
    else:
        tam, adaylar = sarki_ara(uri_veya_sorgu)
    if not tam:
        if adaylar:
            return 'Emin olamadım, işlem yapmadım. Adaylar: ' + '; '.join(f'{_etiket(a)} [{a["uri"]}]' for a in adaylar)
        return 'Eşleşen şarkı bulamadım.'
    metot = 'PUT' if ekle else 'DELETE'
    try:
        _api(metot, '/me/library', {'uris': tam['uri']})
    except SpotifyHata as e:
        if e.kod not in (400, 404):
            raise
        _api(metot, '/me/tracks', body={'ids': [tam['uri'].split(':')[-1]]})
    _gunluk('begen' if ekle else 'begeniyi_kaldir', 'Beğenilen Şarkılar', [tam], uris=[tam['uri']])
    return f'{_etiket(tam)} ' + ('beğenilenlere eklendi.' if ekle else 'beğenilenlerden çıkarıldı.')


def geri_al() -> str:
    gun = [r for r in son_islemler(30) if r.get('eylem') in ('ekle', 'cikar', 'begen', 'begeniyi_kaldir')
           and time.time() - r.get('t', 0) < 6 * 3600]
    if not gun:
        return 'Son 6 saatte geri alınacak bir işlem bulamadım (eski işlemleri elle düzeltmek gerekir).'
    r = gun[-1]
    if r['eylem'] == 'ekle':
        _liste_api('DELETE', r['liste_id'], body={'items': [{'uri': u} for u in r['uris']]})
        msg = f'Geri alındı: "{r["liste"]}" listesine eklenenler çıkarıldı: ' + '; '.join(r['parcalar'])
    elif r['eylem'] == 'cikar':
        _liste_api('POST', r['liste_id'], body={'uris': r['uris']})
        msg = f'Geri alındı: "{r["liste"]}" listesinden çıkarılanlar geri eklendi (listenin sonuna): ' + '; '.join(r['parcalar'])
    elif r['eylem'] == 'begen':
        _api('DELETE', '/me/library', {'uris': ','.join(r['uris'])})
        msg = 'Geri alındı: beğeni kaldırıldı: ' + '; '.join(r['parcalar'])
    else:
        _api('PUT', '/me/library', {'uris': ','.join(r['uris'])})
        msg = 'Geri alındı: yeniden beğenildi: ' + '; '.join(r['parcalar'])
    # aynı işlemi iki kez geri almamak için günlükte işaretle (kayıt kimliğiyle; aynı saniyedeki işlemler karışmaz)
    try:
        p = _ek()._dir() / ISLEM_DOSYASI
        rows = [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
        for x in rows:
            if x.get('id') == r.get('id'):
                x['eylem'] = 'geri_alindi_' + x['eylem']
        p.write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows) + '\n', encoding='utf-8')
    except (OSError, ValueError):
        pass
    _bildir()
    return msg


# --------------------------------------------------------------------------- model aracı
def arac(a, _c=None) -> str:
    a = a or {}
    eylem = str(a.get('eylem') or '').lower()
    liste = str(a.get('liste') or '')
    sarkilar = a.get('sarkilar') or []
    if isinstance(sarkilar, str):
        sarkilar = [sarkilar]
    try:
        if eylem == 'baglan':
            if not _client_id():
                _ek()._hud('ekPanelAc', 'spotify')
                return ('Spotify bağlı değil. Ekranda ODAK › SPOTIFY bölümünü açtım: orada Client ID girilip BAĞLAN\'a '
                        'basılacak. Kullanıcıya bunu kısaca söyle.')
            return baglan()
        if not (settings.get_secret(SECRET) and _client_id()):
            _ek()._hud('ekPanelAc', 'spotify')
            return ('Hata: Spotify liste yönetimi için hesap bağlı değil. ODAK › SPOTIFY bölümünü ekranda açtım; '
                    'kullanıcıya bir kez bağlaması gerektiğini söyle (Premium gerekir).')
        if eylem == 'listeleri_goster':
            return listeleri_goster()
        if eylem == 'liste_icerigi':
            return liste_icerigi(liste)
        if eylem == 'sarki_ekle':
            return sarki_ekle(liste, sarkilar)
        if eylem == 'sarki_cikar':
            return sarki_cikar(liste, sarkilar)
        if eylem == 'calani_listeye_ekle':
            return calani_ekle(liste)
        if eylem == 'liste_olustur':
            return liste_olustur(str(a.get('ad') or liste), bool(a.get('herkese_acik')))
        if eylem == 'begen':
            return kitaplik((sarkilar[0] if sarkilar else 'calan'), True)
        if eylem == 'begenmekten_vazgec':
            return kitaplik((sarkilar[0] if sarkilar else 'calan'), False)
        if eylem == 'geri_al':
            return geri_al()
        if eylem == 'durum':
            d = baglanti_durumu()
            return 'Spotify bağlı: ' + (d['hesap'] or 'hesap adı yok') + ('' if d['premium'] is not False else ' (Premium görünmüyor)')
        return 'Hata: bilinmeyen eylem. Kullanılabilir: listeleri_goster, liste_icerigi, sarki_ekle, sarki_cikar, calani_listeye_ekle, liste_olustur, begen, begenmekten_vazgec, geri_al, baglan.'
    except SpotifyHata as e:
        log('ek: spotify hata', e.kod, e.mesaj[:100])
        return 'Hata: ' + e.mesaj
    except Exception as exc:
        log('ek: spotify beklenmeyen hata', type(exc).__name__, exc)
        return f'Hata: Spotify işlemi yapılamadı ({type(exc).__name__}).'
