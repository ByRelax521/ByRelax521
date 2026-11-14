"""BLOOM — genel MCP köprüsü (Model Context Protocol, stdio istemcisi) ve REA (Reverse Engineer Anything) hazır ayarı.

Neden TEK araç (`mcp`): REA tek başına 229 araç / ~3,8 MB şema sunuyor; bunları sesli oturuma doğrudan kaydetmek imkânsız.
Bu yüzden BLOOM bir "geçit" kullanır: sunucuyu başlatır, araçları ARAR (`ara`), tek aracın şemasını okur (`sema`), çağırır (`cagir`).

  sunucular            kayıtlı sunucular, çalışma durumu, hazır ayarlar
  kur_rea              REA'yı kaydeder (npx -y rea-agents@<sürüm> mcp; Node sürümü denetlenir) — ÖNİZLEME + açık onay
  ekle / sil           başka bir MCP sunucusu kaydeder / kaldırır (ekle: ÖNİZLEME + açık onay, komut bilgisayarında çalışır)
  ara                  sunucunun araçlarında sorguyla arama
  sema                 tek aracın girdi şeması
  cagir                aracı çağırır; salt-okunur (readOnlyHint) olmayan araçlar onay=true ister; uzun çağrılar arka plan işi olur
  kapat                sunucu sürecini durdurur (boşta 15 dk sonra kendiliğinden kapanır)

Protokol: satır-ayrık JSON-RPC 2.0 (stdin/stdout). Sunucudan gelen istekler (roots, sampling vb.) reddedilir; stderr okunup saklanır.
Tam çıktılar `ek/mcp-cikti/` altına yazılır, modele ~6000 karakter verilir.
"""

from __future__ import annotations
import atexit
import collections
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from .log import log

PROTOKOL = '2025-06-18'
ONAY_SURESI = 900
BOSTA_KAPAN = 900
MAX_CIKTI = 6000
HAZIR_BEKLE = 20.0
CAGRI_BEKLE = 18.0
CAGRI_MAX = 900.0
MAX_SUNUCU = 4
KONFIG = 'mcp.json'
_BASLAT = subprocess.Popen      # testte değiştirilebilir
_L = threading.RLock()
_S: dict[str, 'Sunucu'] = {}
_bekleyen: dict[str, dict] = {}

REA_SURUM = '6.8.0'
HAZIR = {
    'rea': {
        'komut': ['npx', '-y', f'rea-agents@{REA_SURUM}', 'mcp'],
        'aciklama': 'REA (Reverse Engineer Anything, github.com/morluto/rea, MIT): yazılımı (ikili dosya, Electron/JS uygulaması, APK vb.) statik analiz eden 229 araçlı MCP sunucusu. '
                    'Yerel ikili analiz için kullanıcının KENDİ Ghidra/Hopper/IDA kurulumu gerekir; JS/Electron analizi ek program istemez.',
        'node': True,
    },
}
# rea-agents engines: ^22.23.4 || ^24.22.1 || >=26.12.1
NODE_ISTENEN = {22: (22, 23, 4), 24: (24, 22, 1)}
NODE_26 = (26, 12, 1)


# --------------------------------------------------------------------------- yapılandırma
def _ek():
    from . import ek
    return ek


def _konfig() -> dict:
    d = _ek()._read_json(KONFIG, {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault('sunucular', {})
    return d


def _konfig_yaz(d: dict) -> None:
    _ek()._write_json(KONFIG, d)


def _cikti_dizini():
    p = _ek()._dir() / 'mcp-cikti'
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _ad_temiz(ad: str) -> str:
    return re.sub(r'[^a-z0-9_-]+', '-', str(ad or '').strip().lower()).strip('-')[:24]


def _komut_ayir(komut) -> list[str]:
    if isinstance(komut, (list, tuple)):
        return [str(x) for x in komut if str(x).strip()]
    try:
        return shlex.split(str(komut or ''), posix=(os.name != 'nt'))
    except ValueError:
        return []


# --------------------------------------------------------------------------- Node sürümü
def node_surumu() -> tuple[int, int, int] | None:
    yol = shutil.which('node')
    if not yol:
        return None
    try:
        kw = {'creationflags': 0x08000000} if os.name == 'nt' else {}
        c = subprocess.run([yol, '--version'], capture_output=True, text=True, timeout=10, **kw)
        m = re.match(r'v?(\d+)\.(\d+)\.(\d+)', (c.stdout or '').strip())
        return tuple(int(x) for x in m.groups()) if m else None
    except Exception:
        return None


def node_uygun(v: tuple[int, int, int] | None) -> tuple[bool, str]:
    if v is None:
        return False, 'Node.js bulunamadı. REA için Node.js 24 LTS (nodejs.org) kurulmalı; kurduktan sonra BLOOM yeniden başlatılmalı.'
    yazi = '.'.join(map(str, v))
    if v[0] >= 26:
        ok = v >= NODE_26
    else:
        ok = v[0] in NODE_ISTENEN and v >= NODE_ISTENEN[v[0]]
    if ok:
        return True, f'Node.js {yazi} uygun.'
    return False, (f'Node.js {yazi} bu REA sürümü için uygun değil (gerekli: 22.23.4+, 24.22.1+ ya da 26.12.1+). '
                   'Node.js 24 LTS kurup BLOOM\'u yeniden başlatmak gerekir.')


# --------------------------------------------------------------------------- süreç + JSON-RPC
class Sunucu:
    def __init__(self, ad: str, komut: list[str], env: dict | None = None):
        self.ad, self.komut, self.env = ad, list(komut), dict(env or {})
        self.p = None
        self.araclar: list[dict] = []
        self.bilgi: dict = {}
        self.hazir = threading.Event()
        self.hata = ''
        self._id = 0
        self._bek: dict[int, dict] = {}
        self._kilit = threading.Lock()
        self.stderr = collections.deque(maxlen=40)
        self.son_kullanim = time.time()
        self.kapali = False
        self.oturum_onay = False

    # -- altyapı
    def _yaz(self, obj: dict) -> None:
        satir = json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n'
        with self._kilit:
            self.p.stdin.write(satir.encode('utf-8'))
            self.p.stdin.flush()

    def _oku(self) -> None:
        try:
            for ham in iter(self.p.stdout.readline, b''):
                try:
                    m = json.loads(ham.decode('utf-8', 'replace'))
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                if 'method' in m and 'id' in m:          # sunucu → istemci isteği: desteklenmiyor
                    try:
                        self._yaz({'jsonrpc': '2.0', 'id': m['id'], 'error': {'code': -32601, 'message': 'istemci bu isteği desteklemiyor'}})
                    except Exception:
                        pass
                elif 'id' in m:
                    b = self._bek.get(m['id'])
                    if b is not None:
                        b['yanit'] = m
                        b['olay'].set()
        except Exception as exc:
            log('ek_mcp: okuma bitti', self.ad, exc)
        finally:
            self.kapali = True
            for b in list(self._bek.values()):
                b.setdefault('yanit', {'error': {'message': 'sunucu süreci kapandı' + self._stderr_ozet()}})
                b['olay'].set()

    def _hata_oku(self) -> None:
        try:
            for ham in iter(self.p.stderr.readline, b''):
                s = ham.decode('utf-8', 'replace').rstrip()
                if s:
                    self.stderr.append(s[:300])
        except Exception:
            pass

    def _stderr_ozet(self) -> str:
        s = list(self.stderr)[-4:]
        return (' — stderr: ' + ' | '.join(s)) if s else ''

    def istek(self, yontem: str, params: dict | None = None, bekle: float = 60.0, iptal=None):
        if self.kapali or self.p is None:
            raise RuntimeError('sunucu çalışmıyor' + self._stderr_ozet())
        with self._kilit:
            self._id += 1
            kimlik = self._id
        b = {'olay': threading.Event()}
        self._bek[kimlik] = b
        try:
            self._yaz({'jsonrpc': '2.0', 'id': kimlik, 'method': yontem, 'params': params or {}})
            bitis = time.monotonic() + bekle
            while not b['olay'].wait(0.5):
                if iptal and iptal():
                    self._bildir('notifications/cancelled', {'requestId': kimlik, 'reason': 'kullanıcı iptal etti'})
                    raise RuntimeError('iptal edildi')
                if time.monotonic() > bitis:
                    self._bildir('notifications/cancelled', {'requestId': kimlik, 'reason': 'zaman aşımı'})
                    raise TimeoutError(f'{yontem} {bekle:.0f} sn içinde yanıtlanmadı')
            y = b['yanit']
            if 'error' in y:
                e = y['error'] or {}
                raise RuntimeError(f'MCP hatası {e.get("code", "")}: {str(e.get("message", ""))[:300]}')
            return y.get('result')
        finally:
            self._bek.pop(kimlik, None)

    def _bildir(self, yontem: str, params: dict | None = None) -> None:
        try:
            self._yaz({'jsonrpc': '2.0', 'method': yontem, 'params': params or {}})
        except Exception:
            pass

    # -- yaşam döngüsü
    def baslat(self) -> None:
        try:
            exe = self.komut[0]
            yol = shutil.which(exe) or exe
            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in self.env.items()})
            kw = {'creationflags': 0x08000000} if os.name == 'nt' else {}
            self.p = _BASLAT([yol, *self.komut[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **kw)
            threading.Thread(target=self._oku, daemon=True, name='mcp-oku').start()
            threading.Thread(target=self._hata_oku, daemon=True, name='mcp-hata').start()
            r = self.istek('initialize', {'protocolVersion': PROTOKOL, 'capabilities': {},
                                          'clientInfo': {'name': 'jarvis', 'version': '3.6'}}, bekle=120)
            self.bilgi = (r or {}).get('serverInfo') or {}
            self._bildir('notifications/initialized')
            tum, imlec = [], None
            for _ in range(40):
                r = self.istek('tools/list', {'cursor': imlec} if imlec else {}, bekle=90) or {}
                tum.extend(t for t in (r.get('tools') or []) if isinstance(t, dict) and t.get('name'))
                imlec = r.get('nextCursor')
                if not imlec:
                    break
            self.araclar = tum
            self.hata = ''
        except Exception as exc:
            self.hata = f'{type(exc).__name__}: {str(exc)[:300]}{self._stderr_ozet()}'
            log('ek_mcp: başlatılamadı', self.ad, self.hata)
            self.kapat()
        finally:
            self.hazir.set()

    def kapat(self) -> None:
        self.kapali = True
        p = self.p
        if p is None:
            return
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        except Exception:
            pass

    def calisiyor(self) -> bool:
        return bool(self.p is not None and not self.kapali and self.p.poll() is None)


def _kapat_hepsi() -> None:
    for s in list(_S.values()):
        try:
            s.kapat()
        except Exception:
            pass


atexit.register(_kapat_hepsi)
_bekci = {'var': False}


def _bekci_baslat() -> None:
    if _bekci['var']:
        return
    _bekci['var'] = True

    def d():
        while True:
            time.sleep(60)
            with _L:
                for ad, s in list(_S.items()):
                    if s.hazir.is_set() and (not s.calisiyor() or time.time() - s.son_kullanim > BOSTA_KAPAN):
                        s.kapat()
                        _S.pop(ad, None)
    threading.Thread(target=d, daemon=True, name='mcp-bekci').start()


def _sunucu_al(ad: str):
    """(Sunucu | None, hata_metni). Hazır değilse en çok HAZIR_BEKLE sn bekler; başlatma ağır ise arka planda sürer."""
    ad = _ad_temiz(ad)
    kayit = _konfig()['sunucular'].get(ad)
    if not kayit:
        return None, f'“{ad or "?"}” adlı kayıtlı MCP sunucusu yok. mcp(eylem=sunucular) ile bak; REA için kur_rea.'
    with _L:
        s = _S.get(ad)
        if s is not None and s.hazir.is_set() and not s.calisiyor():
            _S.pop(ad, None)
            s = None
        if s is None:
            if len([x for x in _S.values() if x.calisiyor() or not x.hazir.is_set()]) >= MAX_SUNUCU:
                return None, f'En fazla {MAX_SUNUCU} MCP sunucusu açık olabilir; mcp(eylem=kapat) ile birini kapat.'
            if kayit.get('node'):
                ok, ileti = node_uygun(node_surumu())
                if not ok:
                    return None, ileti
            s = Sunucu(ad, kayit['komut'], kayit.get('env'))
            _S[ad] = s
            threading.Thread(target=s.baslat, daemon=True, name='mcp-baslat').start()
            _bekci_baslat()
    if not s.hazir.wait(HAZIR_BEKLE):
        return None, (f'“{ad}” sunucusu başlatılıyor (ilk çalıştırmada paket indirilebilir; 1-2 dk sürebilir). '
                      'Yarım dakika sonra aynı isteği yeniden dene; başka bir şey yapabilirsin.')
    if s.hata or not s.calisiyor():
        _S.pop(ad, None)
        return None, f'“{ad}” sunucusu başlamadı: {s.hata or "süreç kapandı"}'
    s.son_kullanim = time.time()
    return s, ''


# --------------------------------------------------------------------------- araçlar
def _kisalt(m: str, n: int = 140) -> str:
    return ' '.join(str(m or '').split())[:n]


def _salt_okunur(t: dict) -> bool:
    return bool(((t or {}).get('annotations') or {}).get('readOnlyHint') is True)


def _risk(t: dict) -> str:
    """okuma: onay gerekmez · orta: açıkça yıkıcı DEĞİL diye işaretli (oturum başına tek onay) · yuksek: yıkıcı ya da işaretsiz (her çağrıda onay).
    REA araçlarının çoğu readOnlyHint=false ama destructiveHint=false (oturum durumu tutar) — bu yüzden orta sınıfı var."""
    an = (t or {}).get('annotations')
    if not isinstance(an, dict) or not an:
        return 'yuksek'
    if an.get('readOnlyHint') is True:
        return 'okuma'
    if an.get('destructiveHint') is False:
        return 'orta'
    return 'yuksek'


def _ara(s: Sunucu, sorgu: str, n: int = 12) -> str:
    jet = [j for j in re.split(r'[^0-9a-zçğıöşü_]+', str(sorgu or '').lower()) if len(j) > 1]
    puan = []
    for t in s.araclar:
        ad = t['name'].lower()
        ac = str(t.get('description') or '').lower()
        sk = sum((6 if j in ad else 0) + (2 if j in ac else 0) for j in jet) if jet else 1
        if sk:
            puan.append((sk, t))
    puan.sort(key=lambda x: (-x[0], x[1]['name']))
    if not puan:
        return f'“{sorgu}” için araç bulunamadı ({len(s.araclar)} araç var). Başka anahtar kelime dene (İngilizce arama genelde daha iyi).'
    satir = [f'{s.ad}: {len(s.araclar)} araç; “{sorgu}” için ilk {min(n, len(puan))}:']
    for _, t in puan[:n]:
        etiket = {'okuma': '', 'orta': ' [yan etki olabilir]', 'yuksek': ' [onay gerekir]'}[_risk(t)]
        satir.append(f'- {t["name"]}{etiket} — {_kisalt(t.get("description"), 130)}')
    satir.append('Ayrıntı: mcp(eylem=sema, arac=…); çağırmak için mcp(eylem=cagir, arac=…, arguman=\'{…}\').')
    return '\n'.join(satir)


_RISK_METIN = {'okuma': 'salt-okunur', 'orta': 'yan etkisi olabilir, yıkıcı değil (oturumda bir kez onay)', 'yuksek': 'yıkıcı ya da işaretsiz (her çağrıda onay=true)'}


def _sema(s: Sunucu, ad: str) -> str:
    t = next((x for x in s.araclar if x['name'] == ad), None)
    if t is None:
        yakin = [x['name'] for x in s.araclar if ad.lower() in x['name'].lower()][:8]
        return f'“{ad}” adlı araç yok.' + (f' Benzer: {", ".join(yakin)}' if yakin else ' mcp(eylem=ara) ile ara.')
    sema = json.dumps(t.get('inputSchema') or {}, ensure_ascii=False)
    if len(sema) > 3500:
        sema = sema[:3500] + ' …(kısaltıldı)'
    return (f'{t["name"]} — {_kisalt(t.get("description"), 400)}\nRisk: {_RISK_METIN[_risk(t)]}\n'
            f'girdi şeması: {sema}')


def _sonuc_metni(r) -> tuple[str, bool]:
    r = r or {}
    parcalar = []
    for c in (r.get('content') or []):
        if not isinstance(c, dict):
            continue
        if c.get('type') == 'text':
            parcalar.append(str(c.get('text') or ''))
        elif c.get('type') in ('image', 'audio'):
            parcalar.append(f'[{c.get("type")} içeriği atlandı]')
        elif c.get('type') == 'resource':
            rs = c.get('resource') or {}
            parcalar.append(str(rs.get('text') or f'[kaynak {rs.get("uri", "")}]'))
        else:
            parcalar.append(f'[{c.get("type")}]')
    if not parcalar and r.get('structuredContent') is not None:
        parcalar.append(json.dumps(r['structuredContent'], ensure_ascii=False))
    return '\n'.join(parcalar).strip() or '(boş yanıt)', bool(r.get('isError'))


def _cikti_ver(is_id: str, ad: str, arac: str, metin: str, hata: bool) -> str:
    dosya = ''
    if len(metin) > MAX_CIKTI:
        try:
            p = _cikti_dizini() / re.sub(r'[^A-Za-z0-9_.-]+', '_', f'{is_id}-{ad}-{arac}.txt')
            p.write_text(metin, encoding='utf-8')
            dosya = str(p)
        except OSError:
            pass
        metin = metin[:MAX_CIKTI] + f'\n…(kısaltıldı; toplam {len(metin)} karakter' + (f', tam çıktı: {dosya}' if dosya else '') + ')'
    return ('[araç HATA döndürdü] ' if hata else '') + metin


def _cagir_is(s: Sunucu, arac: str, arguman: dict, is_id: str, k_iptal) -> str:
    from . import ek_isler
    ek_isler.olay(is_id, f'{s.ad}.{arac} çağrılıyor')
    try:
        r = s.istek('tools/call', {'name': arac, 'arguments': arguman}, bekle=CAGRI_MAX, iptal=k_iptal)
    except TimeoutError as exc:
        ek_isler.olay(is_id, 'zaman aşımı: ' + str(exc))
        raise
    metin, hata = _sonuc_metni(r)
    ek_isler.olay(is_id, f'yanıt alındı ({len(metin)} karakter{", HATA" if hata else ""})')
    return _cikti_ver(is_id, s.ad, arac, metin, hata)


def _cagir(a: dict) -> str:
    from . import ek_isler
    ad = _ad_temiz(a.get('sunucu') or 'rea')
    arac = str(a.get('arac') or '').strip()
    if not arac:
        return 'arac adı gerekli (mcp eylem=ara ile bul).'
    arg = a.get('arguman') if a.get('arguman') not in (None, '') else {}
    if isinstance(arg, str):
        try:
            arg = json.loads(arg)
        except ValueError:
            return 'arguman geçerli JSON değil. Örnek: {"path": "C:/x.exe"} — şemayı mcp(eylem=sema) ile oku.'
    if not isinstance(arg, dict):
        return 'arguman bir JSON nesnesi olmalı.'
    s, hata = _sunucu_al(ad)
    if s is None:
        return hata
    t = next((x for x in s.araclar if x['name'] == arac), None)
    if t is None:
        return _sema(s, arac)
    risk = _risk(t)
    onayli = a.get('onay') is True
    if risk == 'yuksek' and not onayli or risk == 'orta' and not onayli and not s.oturum_onay:
        return (f'ONAY GEREKİR: “{arac}” aracı salt-okunur değil ' + ('(yıkıcı olabilir ya da güvenlik işareti yok; her çağrıda onay istenir)' if risk == 'yuksek'
                else '(dosya/oturum durumu değiştirebilir; yıkıcı değil. Onay bu oturumda “' + ad + '” sunucusundaki benzer araçlar için bir kez istenir)') + '.\n'
                f'Açıklama: {_kisalt(t.get("description"), 260)}\nArgümanlar: {_kisalt(json.dumps(arg, ensure_ascii=False), 300)}\n'
                'Kullanıcıya ne yapılacağını söyle, açık onay gelirse aynı çağrıyı onay=true ile tekrarla.')
    if risk == 'orta' and onayli:
        s.oturum_onay = True
    try:
        kayit = ek_isler.yeni('mcp', f'{ad}: {arac}', {'sunucu': ad, 'arac': arac})
    except ek_isler.Dolu as exc:
        return str(exc)
    is_id = kayit['id']
    son: dict = {}
    bitti = threading.Event()
    kilit = threading.Lock()
    durum = {'arka': False, 'teslim': False}

    def teslim():
        with kilit:
            if durum['teslim']:
                return
            durum['teslim'] = True
        try:
            ek_isler.teslim_et('mcp:' + is_id, f'[MCP İŞİ BİTTİ {ad}.{arac}] ' + (son.get('metin') or ('HATA: ' + son.get('hata', '?')))[:1400])
        except Exception:
            pass

    def is_():
        try:
            son['metin'] = _cagir_is(s, arac, arg, is_id, lambda: ek_isler.iptal_istendi(is_id))
            ek_isler.bitir(is_id, 'bitti', son['metin'][:600], 'tamamlandı')
        except Exception as exc:
            son['hata'] = str(exc)[:400]
            ip = 'iptal' in str(exc)
            ek_isler.bitir(is_id, 'iptal' if ip else 'hata', son['hata'], 'iptal edildi' if ip else 'hata: ' + son['hata'][:100])
        finally:
            s.son_kullanim = time.time()
            bitti.set()
            if durum['arka']:
                teslim()
    threading.Thread(target=is_, daemon=True, name='mcp-cagri').start()
    if bitti.wait(CAGRI_BEKLE):
        return son.get('metin') or ('HATA: ' + son.get('hata', '?'))
    durum['arka'] = True
    if bitti.is_set():          # tam sınırda bitti
        return son.get('metin') or ('HATA: ' + son.get('hata', '?'))
    return (f'{ad}.{arac} uzun sürüyor; ARKA PLAN işi olarak sürüyor ([{is_id}]). Bitince sonuç otomatik iletilir; '
            'bu sırada başka konuşabilirsiniz, durum için isler(eylem=durum).')


# --------------------------------------------------------------------------- kayıt (onaylı)
def _kaydet_onayli(ad: str, komut: list[str], env: dict, node: bool, onay: bool, aciklama: str = '') -> str:
    if not komut:
        return 'komut boş.'
    anahtar = ad + '|' + ' '.join(komut)
    for k in [k for k, v in _bekleyen.items() if time.time() - v['t'] > ONAY_SURESI]:
        _bekleyen.pop(k, None)
    if not onay:
        _bekleyen[anahtar] = {'t': time.time()}
        ek = ''
        if node:
            ok, ileti = node_uygun(node_surumu())
            ek = f'\nNode durumu: {ileti}'
        return ('ÖNİZLEME — henüz kaydedilmedi.\n'
                f'Sunucu adı: {ad}\nÇalışacak komut (bilgisayarında): {" ".join(komut)}\n'
                + (f'{aciklama}\n' if aciklama else '')
                + 'Bu komut kullanıcının bilgisayarında program olarak çalışır (npx ilk seferde paketi internetten indirir). '
                  'Bunu kullanıcıya açıkça söyle; açık onay verirse aynı çağrıyı onay=true ile tekrarla.' + ek)
    if anahtar not in _bekleyen:
        return 'Önce önizleme gerekir (onay=true olmadan aynı çağrıyı yap, kullanıcıya göster, onay al).'
    _bekleyen.pop(anahtar, None)
    d = _konfig()
    if len(d['sunucular']) >= 12 and ad not in d['sunucular']:
        return 'En fazla 12 MCP sunucusu kayıtlı olabilir; mcp(eylem=sil) ile birini kaldır.'
    d['sunucular'][ad] = {'komut': komut, 'env': env, 'node': bool(node), 'ekle': time.time()}
    _konfig_yaz(d)
    return f'“{ad}” MCP sunucusu kaydedildi. Kullanmak için mcp(eylem=ara, sunucu="{ad}", sorgu=…). İlk kullanımda başlatılır.'


def arac(a: dict, _c=None) -> str:
    a = a or {}
    eylem = str(a.get('eylem') or 'sunucular').lower()
    try:
        if eylem == 'sunucular':
            d = _konfig()['sunucular']
            satir = []
            for ad, k in d.items():
                s = _S.get(ad)
                dur = f'çalışıyor, {len(s.araclar)} araç' if s and s.hazir.is_set() and s.calisiyor() else ('başlatılıyor' if s and not s.hazir.is_set() else 'kapalı')
                satir.append(f'- {ad} [{dur}]: {" ".join(k.get("komut", []))}')
            hazir = [f'- {ad}: {h["aciklama"]} (kur_rea ile kaydedilir)' for ad, h in HAZIR.items() if ad not in d]
            return ('Kayıtlı MCP sunucuları:\n' + '\n'.join(satir) if satir else 'Kayıtlı MCP sunucusu yok.') + ('\nHazır ayar:\n' + '\n'.join(hazir) if hazir else '')
        if eylem == 'kur_rea':
            h = HAZIR['rea']
            return _kaydet_onayli('rea', h['komut'], {}, True, a.get('onay') is True, h['aciklama'])
        if eylem == 'ekle':
            ad = _ad_temiz(a.get('ad') or a.get('sunucu'))
            komut = _komut_ayir(a.get('komut'))
            if not ad or not komut:
                return 'ad ve komut gerekli (ör. ad=dosyalar, komut="npx -y @modelcontextprotocol/server-filesystem C:/Belgeler").'
            if any(c in str(a.get('komut')) for c in ('|', '&&', ';', '>', '<', '`', '$(')):
                return 'Komutta kabuk işaretleri (| && ; > <) kullanılamaz; yalnızca tek program ve argümanları.'
            return _kaydet_onayli(ad, komut, {}, komut[0].lower() in ('npx', 'npx.cmd', 'node'), a.get('onay') is True)
        if eylem == 'sil':
            ad = _ad_temiz(a.get('ad') or a.get('sunucu'))
            d = _konfig()
            if ad not in d['sunucular']:
                return f'“{ad}” kayıtlı değil.'
            d['sunucular'].pop(ad)
            _konfig_yaz(d)
            s = _S.pop(ad, None)
            if s:
                s.kapat()
            return f'“{ad}” kaldırıldı.'
        if eylem == 'kapat':
            ad = _ad_temiz(a.get('ad') or a.get('sunucu'))
            hedef = [ad] if ad else list(_S)
            for x in hedef:
                s = _S.pop(x, None)
                if s:
                    s.kapat()
            return f'Kapatıldı: {", ".join(hedef) or "açık sunucu yoktu"}.'
        if eylem in ('ara', 'sema'):
            s, hata = _sunucu_al(a.get('sunucu') or 'rea')
            if s is None:
                return hata
            if eylem == 'ara':
                return _ara(s, str(a.get('sorgu') or a.get('arac') or ''))
            return _sema(s, str(a.get('arac') or ''))
        if eylem == 'cagir':
            return _cagir(a)
        return 'Bilinmeyen eylem. Geçerli: sunucular, kur_rea, ekle, sil, ara, sema, cagir, kapat.'
    except Exception as exc:
        log('ek_mcp: hata', eylem, exc)
        return f'MCP hatası: {type(exc).__name__}: {str(exc)[:300]}'
