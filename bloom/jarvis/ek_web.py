"""BLOOM EK — Mark 2 web ekranı (jarvis-main arayüzü) için yerel sunucu.

* Arayüz dosyaları exe'ye gömülüdür (ek_web_dosya: dist → zip → base64). Yalnızca bu bilgisayarda (127.0.0.1) çalışır;
  Host/Origin denetimi vardır (DNS yeniden bağlama ve başka siteler okuyamaz).
* /api/dashboard : hava + döviz + haber panosu (ek_pano). Başka veri yok; BLOOM'un durumu (konuşma, panel, mikrofon…)
  sunucudan değil, HUD sayfasından postMessage ile gelir (ek_hud: bloom-web.js).
* /api/kitaplik… : El Kontrolü'ndeki kitaplık için küçük yerel kayıt (kitaplik.json). Tarama/doldurma (görüntüden tanıma)
  bu sürümde yok; istek açık bir hatayla döner.
* /mediapipe/wasm/…, /models/… : El Kontrolü varlıkları exe'de değil, isteğe bağlı `el-varliklari` klasöründedir (exe'nin yanında).
"""
from __future__ import annotations
import base64
import io
import json
import mimetypes
import os
import re
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .log import log

PORT = 47834
_L = threading.RLock()
_W = {'port': 0, 'srv': None, 'dosyalar': None}
MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
        '.svg': 'image/svg+xml', '.json': 'application/json', '.wasm': 'application/wasm', '.png': 'image/png',
        '.task': 'application/octet-stream', '.tflite': 'application/octet-stream', '.webmanifest': 'application/manifest+json'}


# --------------------------------------------------------------------------- dosyalar
def dosyalar() -> dict[str, bytes]:
    with _L:
        if _W['dosyalar'] is None:
            d: dict[str, bytes] = {}
            try:
                from . import ek_web_dosya
                z = zipfile.ZipFile(io.BytesIO(base64.b64decode(ek_web_dosya.ZIP_B64)))
                for n in z.namelist():
                    if not n.endswith('/'):
                        d[n] = z.read(n)
            except Exception as exc:
                log('ek_web: gömülü dosyalar okunamadı', type(exc).__name__, exc)
            _W['dosyalar'] = d
    return _W['dosyalar']


def el_klasorleri() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get('EK_EL_DIR')
    if env:
        out.append(Path(env))
    try:
        exe = Path(sys.executable).resolve().parent
        out += [exe / 'el-varliklari', exe / '_internal' / 'el-varliklari', exe.parent / 'el-varliklari']
    except Exception:
        pass
    try:
        from . import paths
        out.append(Path(paths.DATA_DIR) / 'ek' / 'el-varliklari')
    except Exception:
        pass
    return out


def el_varligi(ad: str) -> bytes | None:
    """ad: 'mediapipe/wasm/x.wasm' ya da 'models/y.task'"""
    if '..' in ad or '\\' in ad or ad.startswith('/'):
        return None
    for k in el_klasorleri():
        try:
            p = (k / ad).resolve()
            if p.is_file() and str(p).startswith(str(k.resolve())):
                return p.read_bytes()
        except OSError:
            continue
    return None


def el_hazir() -> bool:
    return el_varligi('mediapipe/wasm/vision_wasm_internal.wasm') is not None


# --------------------------------------------------------------------------- kitaplık (küçük yerel kayıt)
def _kitaplik_yolu() -> Path:
    from . import paths
    return Path(paths.DATA_DIR) / 'kitaplik.json'


def kitaplik_oku() -> dict:
    try:
        d = json.loads(_kitaplik_yolu().read_text('utf-8'))
        if isinstance(d, dict) and isinstance(d.get('kitaplar'), list):
            return {'kitaplar': d['kitaplar'], 'referans': d.get('referans')}
    except Exception:
        pass
    return {'kitaplar': [], 'referans': None}


def kitaplik_yaz(d: dict) -> dict:
    d = {'kitaplar': [k for k in (d.get('kitaplar') or []) if isinstance(k, dict)][:500], 'referans': d.get('referans')}
    try:
        p = _kitaplik_yolu()
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(d, ensure_ascii=False), 'utf-8')
        os.replace(tmp, p)
    except OSError as exc:
        log('ek_web: kitaplık yazılamadı', exc)
    return d


# --------------------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = 'BloomWeb'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        h = (self.headers.get('Host') or '').strip().lower()
        p = _W['port']
        return h in (f'127.0.0.1:{p}', f'localhost:{p}')

    def _origin_ok(self) -> bool:
        p = _W['port']
        o = self.headers.get('Origin')
        if o is not None and o not in (f'http://127.0.0.1:{p}', f'http://localhost:{p}'):
            return False
        return self.headers.get('Sec-Fetch-Site') in (None, 'same-origin', 'none')

    def _cevap(self, kod: int, govde: bytes = b'', tur: str = 'text/plain; charset=utf-8', onbellek: str = 'no-store') -> None:
        self.send_response(kod)
        self.send_header('Content-Type', tur)
        self.send_header('Content-Length', str(len(govde)))
        self.send_header('Cache-Control', onbellek)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        if govde and self.command != 'HEAD':
            self.wfile.write(govde)

    def _json(self, kod: int, obj) -> None:
        self._cevap(kod, json.dumps(obj, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def _govde(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return {}
        if n > 8 * 1024 * 1024:
            raise ValueError('boyut')
        d = json.loads(self.rfile.read(n).decode('utf-8'))
        return d if isinstance(d, dict) else {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if not self._host_ok():
                return self._cevap(403, b'host')
            yol = self.path.split('?', 1)[0]
            if yol == '/api/dashboard':
                from . import ek_pano
                return self._json(200, ek_pano.pano())
            if yol == '/api/kitaplik':
                return self._json(200, kitaplik_oku())
            if yol in ('/api/surum', '/api/ozellikler', '/api/log'):
                from . import ek_surum
                if yol == '/api/surum':
                    return self._json(200, {**ek_surum.bilgi(), 'metin': ek_surum.surum_metni()})
                if yol == '/api/ozellikler':
                    return self._json(200, {'surum': ek_surum.SURUM, 'kategoriler': ek_surum.ozellikler_veri(), 'komutlar': ek_surum.EKRAN_KOMUTLARI})
                try:
                    n = int((re.search(r'(?:^|&)n=(\d+)', self.path.partition('?')[2]) or [0, 300])[1])
                except (TypeError, ValueError):
                    n = 300
                return self._json(200, {'satirlar': ek_surum.log_son(n)})
            if yol == '/api/saglik':
                return self._json(200, {'ok': True, 'el': el_hazir()})
            if yol.startswith('/api/'):
                return self._json(404, {'error': 'yok'})
            ad = yol.lstrip('/') or 'index.html'
            if '..' in ad or '\\' in ad:
                return self._cevap(404, b'yok')
            if ad.startswith(('mediapipe/', 'models/')):
                v = el_varligi(ad)
                if v is None:
                    return self._cevap(404, b'yok')
                return self._cevap(200, v, MIME.get(os.path.splitext(ad)[1].lower(), 'application/octet-stream'), 'max-age=86400')
            v = dosyalar().get(ad)
            if v is None:
                return self._cevap(404, b'yok')
            ext = os.path.splitext(ad)[1].lower()
            self._cevap(200, v, MIME.get(ext) or mimetypes.guess_type(ad)[0] or 'application/octet-stream')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log('ek_web: GET hatası', type(exc).__name__, exc)
            try:
                self._cevap(500, b'hata')
            except Exception:
                pass

    def _yaz(self, yontem: str) -> None:
        try:
            if not self._host_ok():
                return self._cevap(403, b'host')
            if not self._origin_ok():
                return self._cevap(403, b'origin')
            yol = self.path.split('?', 1)[0]
            m = re.fullmatch(r'/api/kitaplik(?:/([^/]+))?(?:/(not|doldur|kapak))?', yol)
            if not m:
                return self._json(404, {'error': 'yok'})
            kid, alt = m.group(1), m.group(2)
            with _L:
                d = kitaplik_oku()
                kitaplar = d['kitaplar']
                if yontem == 'POST' and kid is None:
                    return self._json(200, kitaplik_yaz({**d, **{k: v for k, v in self._govde().items() if k in ('kitaplar', 'referans')}}))
                if yontem == 'POST' and kid == 'yeni':
                    g = self._govde()
                    ad = str(g.get('ad') or '').strip()[:120]
                    if not ad:
                        return self._json(400, {'error': 'kitap adı boş'})
                    var = next((k for k in kitaplar if str(k.get('ad', '')).casefold() == ad.casefold()), None)
                    if var:
                        return self._json(200, {'kitap': var, 'yeni': False})
                    k = {'id': uuid.uuid4().hex[:10], 'ad': ad, 'yazar': str(g.get('yazar') or '')[:120], 'notlar': [], 'eklendi': int(time.time())}
                    kitaplar.append(k)
                    kitaplik_yaz(d)
                    return self._json(200, {'kitap': k, 'yeni': True})
                if kid in ('tara', 'fotograf'):
                    return self._json(501, {'error': 'Görüntüden kitap tanıma bu sürümde yok.'})
                k = next((x for x in kitaplar if str(x.get('id')) == kid), None)
                if k is None:
                    return self._json(404, {'error': 'kitap bulunamadı'})
                if alt in ('doldur', 'kapak'):
                    return self._json(501, {'error': 'Bu özellik bu sürümde yok.'})
                if yontem == 'DELETE':
                    d['kitaplar'] = [x for x in kitaplar if x is not k]
                    kitaplik_yaz(d)
                    return self._json(200, {'ok': True})
                g = self._govde()
                if alt == 'not':
                    k.setdefault('notlar', []).append({'tur': 'alinti' if g.get('tur') == 'alinti' else 'not', 'metin': str(g.get('metin') or '')[:2000], 'at': int(time.time())})
                else:
                    for f in ('ad', 'yazar', 'ozet'):
                        if f in g:
                            k[f] = str(g[f] or '')[:4000]
                kitaplik_yaz(d)
                return self._json(200, {'kitap': k})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log('ek_web: yazma hatası', type(exc).__name__, exc)
            try:
                self._json(500, {'error': 'hata'})
            except Exception:
                pass

    def do_POST(self):
        self._yaz('POST')

    def do_DELETE(self):
        self._yaz('DELETE')


def baslat() -> int:
    """Hizmeti başlatır; port döner (0 = başlamadı)."""
    with _L:
        if _W['srv'] is not None:
            return _W['port']
        srv = None
        for port in (PORT, 0):
            try:
                srv = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
                break
            except OSError:
                srv = None
        if srv is None:
            log('ek_web: yerel hizmet başlatılamadı')
            return 0
        srv.daemon_threads = True
        _W['srv'] = srv
        _W['port'] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True, name='ek-web-http').start()
    log(f'ek_web: Mark 2 ekran hizmeti 127.0.0.1:{_W["port"]}')
    return _W['port']


def adres() -> str:
    p = _W['port'] or baslat()
    return f'http://127.0.0.1:{p}/index.html' if p and dosyalar() else ''
