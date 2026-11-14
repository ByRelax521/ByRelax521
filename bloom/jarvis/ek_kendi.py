"""BLOOM — kendi koduna İZİNLİ, SALT OKUNUR erişim: hata ayıklama için kaynağı okur, günlükteki hataları kaynakla eşleştirir, düzeltmeyi ÖNERİR.

Neden: Program çok değişti; bir şey bozulunca Bloom'un kendi koduna bakabilmesi gerekiyor. Ama şunları yapmaz:
  * İzin kullanıcının isteğiyle varsayılan AÇIK; Yetenekler sekmesindeki anahtarla ya da sözle kapatılır/açılır. Kapalıyken hiçbir şey okunmaz.
  * YAZMAZ, çalıştırmaz, silmez. Düzeltme `yama_oner` ile ek/yama-onerileri/ altına bir ÖNERİ dosyası (açıklama + diff) olarak yazılır;
    uygulamak kullanıcıya (ya da onayıyla Hermes'e / geliştiriciye) kalır. Paketli exe kendini zaten yeniden yazamaz.
  * Yalnızca bu KÖKLERİN içine bakar (gerçek yol çözülür, `..` ve bağlantılarla dışarı çıkılamaz):
        kaynak klasörü   <exe klasörü>/bloom-kaynak   (ya da BLOOM_KAYNAK ortam değişkeni)   → "jarvis/…", "hud_ek/…"
        HUD dosyaları    paths.HUD_DIR                                                        → "hud/…"
        günlük           paths.LOG_FILE (+ .old.log)                                          → yalnızca `hatalar` / `gunluk` ile
    Ayarlar, bellek, anahtarlar, .env, kişi/fikir verisi bu köklerde YOKTUR ve ayrıca ad kalıplarıyla da reddedilir.
  * Çıktıdaki anahtar/parola benzeri her şey ●●● ile gizlenir (günlük dahil). Yayın modunda sonuçlar zaten sahteyle maskelenir.
DÜRÜST NOT: kaynak kopyası, çalışan programın DECOMPILE edilmiş halidir (işlevlerin ~%82'si bayt koduyla birebir; yamalı olanlar kaynaktan derlenir).
Günlükteki satır numaraları bu dosyalarla birebir tutmayabilir; bu yüzden eşleştirme işlev adı ve günlük metniyle yapılır.
"""

from __future__ import annotations
import ast
import difflib
import os
import re
import sys
import time
from pathlib import Path
from .log import log

IZINLI_UZ = {'.py', '.js', '.css', '.html', '.md', '.txt', '.json', '.tsv', '.sh', '.yaml', '.yml'}
YASAK_AD = re.compile(r'(^\.env|\.pem$|\.key$|secret|credential|id_rsa|\.sqlite|\.db$|\.pfx$)', re.I)
JSON_IZIN = {'yamalar.json'}
MAX_OKU_SATIR = 200
MAX_CIKTI = 7000
MAX_DOSYA_BOYUT = 900_000
MAX_ARA_DOSYA_BOYUT = 300_000
MAX_ONERI = 20
GUNLUK_KUYRUK = 400_000

_SIR = [
    re.compile(r'AIza[0-9A-Za-z_\-]{20,}'),
    re.compile(r'\b(?:sk|gsk|nvapi|xai|ghp|gho|github_pat|hf)[-_][A-Za-z0-9_\-]{16,}'),
    re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}'),
    re.compile(r'(?i)((?:api[_\-]?key|apikey|token|secret|password|passwd|parola|anahtar|authorization)["\'\s]*[:=]\s*["\']?)[^\s"\',;)}\]]{8,}'),
]


def _ek():
    from . import ek
    return ek


def gizle(t: str) -> str:
    t = str(t or '')
    t = _SIR[0].sub('●●●', t)
    t = _SIR[1].sub('●●●', t)
    t = _SIR[2].sub('Bearer ●●●', t)
    t = _SIR[3].sub(lambda m: m.group(1) + '●●●', t)
    return t


def _kes(t: str, n: int = MAX_CIKTI) -> str:
    return t if len(t) <= n else t[:n] + f'\n… (kısaltıldı; {len(t) - n} karakter daha)'


# --------------------------------------------------------------------------- izin
def izinli() -> bool:
    try:
        return bool(_ek().ayar('kendi_kod_izin', True))      # kullanıcının isteğiyle varsayılan AÇIK (salt okunur); anahtardan/sözle kapatılır
    except Exception:
        return False


def izin_ayarla(ver: bool) -> str:
    try:
        _ek().ayar_yaz('kendi_kod_izin', bool(ver))
        _ek()._hud_durum()
    except Exception as exc:
        return f'Hata: izin kaydedilemedi ({type(exc).__name__}).'
    log('ek: kendi koduna okuma izni', 'verildi' if ver else 'kaldırıldı')
    return ('Tamam: kendi kaynak kodumu ve günlüğümü SALT OKUNUR inceleyebilirim. Yazmam, çalıştırmam; düzeltmeyi yalnızca öneri dosyası olarak yazarım.'
            if ver else 'Tamam: kendi koduma okuma izni kaldırıldı.')


def _gerek() -> str:
    if izinli():
        return ''
    return ('İzin yok (kapalı). Kullanıcı kodunu incelemeni istediyse ya da izin verdiyse HEMEN kendi_kod(eylem=izin_ver, kullanici_dedi=true) çağır ve devam et; '
            'istemediyse sor. Kullanıcıya "erişimim yok" deme: izin verince bakabilirsin.')


# --------------------------------------------------------------------------- kökler
def kaynak_koku() -> Path | None:
    adaylar = []
    env = os.environ.get('BLOOM_KAYNAK')
    if env:
        adaylar.append(Path(env))
    try:
        exe = Path(sys.executable).resolve().parent
        adaylar += [exe / 'bloom-kaynak', exe.parent / 'bloom-kaynak']
    except Exception:
        pass
    for a in adaylar:
        try:
            if (a / 'jarvis').is_dir():
                return a.resolve()
        except OSError:
            continue
    return None


def hud_koku() -> Path | None:
    try:
        from . import paths
        p = Path(paths.HUD_DIR)
        return p.resolve() if p.is_dir() else None
    except Exception:
        return None


def _gunluk_yollari() -> list[Path]:
    try:
        from . import paths
        lf = Path(paths.LOG_FILE)
        return [x for x in (lf.with_suffix('.old.log'), lf) if x.is_file()]
    except Exception:
        return []


def _icinde(kok: Path, yol: Path) -> bool:
    try:
        yol.relative_to(kok)
        return True
    except ValueError:
        return False


def coz(gor: str, dizin_ok: bool = False) -> tuple[Path | None, str]:
    """Kullanıcının/modelin verdiği göreli adı gerçek yola çevirir; izinli köklerin dışına çıkamaz."""
    g = str(gor or '').strip().replace('\\', '/').lstrip('/')
    if not g and not dizin_ok:
        return None, 'Hata: dosya adı verilmedi.'
    if re.match(r'^[A-Za-z]:', g) or '\x00' in g:
        return None, 'Hata: mutlak yol / sürücü harfi kabul edilmez; kaynak köküne göre yaz (örn. jarvis/ek_yayin.py).'
    if any(p == '..' for p in g.split('/')):
        return None, 'Hata: ".." kabul edilmez.'
    if g == 'hud' or g.startswith('hud/'):
        kok = hud_koku(); g = g[4:]
        ad = 'HUD klasörü'
    else:
        kok = kaynak_koku(); ad = 'kaynak klasörü'
    if kok is None:
        return None, f'Hata: {ad} bulunamadı' + (' (paketle gelen "bloom-kaynak" klasörü exe\'nin yanında olmalı).' if ad == 'kaynak klasörü' else '.')
    yol = (kok / g).resolve() if g else kok
    if not _icinde(kok, yol):
        return None, 'Hata: bu yol izinli klasörün dışında.'
    if dizin_ok and yol.is_dir():
        return yol, ''
    if yol.is_dir():
        return None, 'Hata: bu bir klasör; liste kullan.'
    if not yol.is_file():
        return None, f'Hata: dosya yok: {g}'
    if YASAK_AD.search(yol.name):
        return None, 'Hata: bu dosyaya erişim yok (gizli bilgi olabilir).'
    uz = yol.suffix.lower()
    if uz not in IZINLI_UZ or (uz == '.json' and yol.name not in JSON_IZIN):
        return None, f'Hata: yalnızca kod/metin dosyaları okunur ({uz or "uzantısız"} değil).'
    if yol.stat().st_size > MAX_DOSYA_BOYUT:
        return None, 'Hata: dosya çok büyük (üretilmiş olabilir); ara ile ilgili yeri bul.'
    return yol, ''


def _goreli(yol: Path) -> str:
    for kok, on in ((kaynak_koku(), ''), (hud_koku(), 'hud/')):
        if kok and _icinde(kok, yol):
            return on + yol.relative_to(kok).as_posix()
    return yol.name


def _metin(yol: Path) -> str:
    return yol.read_text('utf-8', errors='replace')


def _kod_dosyalari(klasor: Path | None = None) -> list[Path]:
    out = []
    for kok in ([klasor] if klasor else [kaynak_koku(), hud_koku()]):
        if not kok:
            continue
        for p in sorted(kok.rglob('*')):
            try:
                if not p.is_file() or p.suffix.lower() not in IZINLI_UZ or YASAK_AD.search(p.name) or '__pycache__' in p.parts:
                    continue
                if not _icinde(kok.resolve(), p.resolve()):
                    continue                      # sembolik bağlantı kök dışına çıkıyor
                if p.suffix.lower() == '.json' and p.name not in JSON_IZIN:
                    continue
                out.append(p.resolve())
            except OSError:
                continue
    return out


# --------------------------------------------------------------------------- eylemler: kaynak
def durum() -> dict:
    k = kaynak_koku()
    return {'izin': izinli(), 'kaynak': bool(k), 'yol': str(k) if k else '', 'hud': bool(hud_koku()),
            'oneri': len(oneriler()), 'gunluk': bool(_gunluk_yollari())}


def harita() -> str:
    k = kaynak_koku()
    if not k:
        return coz('x')[1]
    satir = []
    for p in sorted((k / 'jarvis').glob('*.py')):
        try:
            doc = ast.get_docstring(ast.parse(_metin(p))) or ''
        except (SyntaxError, ValueError, OSError):
            doc = '(ayrıştırılamadı)'
        ilk = doc.strip().splitlines()[0][:110] if doc.strip() else ''
        if p.name.startswith('ek_') or p.name in ('app.py', 'brand.py', 'story.py', 'settings.py', 'paths.py', 'memory.py', 'geo.py', 'panels.py'):
            satir.append(f'jarvis/{p.name}  {ilk}')
    alt = sorted(d.name for d in (k / 'jarvis').iterdir() if d.is_dir() and d.name != '__pycache__')
    ek = ('\nAlt paketler: ' + ', '.join(f'jarvis/{a}/' for a in alt)) if alt else ''
    hm = '\nEk dosyalar: ' + ', '.join(x.name for x in sorted(k.iterdir()) if x.is_file() and x.suffix.lower() in IZINLI_UZ) if k.is_dir() else ''
    return _kes('KAYNAK HARİTASI (ek_* = sonradan yazılanlar; app/brand/story/... = özgün programın decompile hali)\n' + '\n'.join(satir) + ek + hm +
                '\nNot: HUD dosyaları için "hud/hud.js" gibi yaz. Çalışan kod bayt kodudur; bu kaynak %82 birebir.')


def liste(klasor: str = '') -> str:
    yol, hata = coz(klasor, dizin_ok=True)
    if hata:
        return hata
    if not yol.is_dir():
        return 'Hata: klasör değil.'
    s = []
    for p in sorted(yol.iterdir()):
        if p.name == '__pycache__':
            continue
        if p.is_dir():
            s.append(f'{p.name}/')
        elif (p.suffix.lower() in IZINLI_UZ and not YASAK_AD.search(p.name) and not (p.suffix.lower() == '.json' and p.name not in JSON_IZIN)
              and _icinde(yol, p.resolve())):
            try:
                n = _metin(p).count('\n') + 1
            except OSError:
                n = 0
            s.append(f'{p.name}  ({n} satır)')
    ad = _goreli(yol)
    return _kes(f'{"(kök)" if ad in ("", ".") else ad}:\n' + ('\n'.join(s) if s else '(boş)'))


def oku(dosya: str, bas=1, son=None) -> str:
    yol, hata = coz(dosya)
    if hata:
        return hata
    satirlar = _metin(yol).splitlines()
    try:
        b = max(1, int(bas or 1))
        e = int(son) if son else b + MAX_OKU_SATIR - 1
    except (TypeError, ValueError):
        return 'Hata: satır numaraları sayı olmalı.'
    e = min(e, b + MAX_OKU_SATIR - 1, len(satirlar))
    if b > len(satirlar):
        return f'Hata: dosyada {len(satirlar)} satır var.'
    parca, toplam = [], 0
    for i in range(b, e + 1):
        ln = gizle(f'{i:>5}  {satirlar[i - 1][:400]}')
        if toplam + len(ln) > MAX_CIKTI - 200 and parca:
            e = i - 1
            break
        parca.append(ln); toplam += len(ln) + 1
    son_not = f'\n… devamı için baslangic={e + 1}' if e < len(satirlar) else ''
    return f'{_goreli(yol)}  [{b}-{e} / {len(satirlar)}]\n' + '\n'.join(parca) + son_not


def ara(desen: str, klasor: str = '', regex: bool = False, buyuk: bool = False, en_cok: int = 30) -> str:
    desen = str(desen or '')
    if len(desen) < 2:
        return 'Hata: aranacak metin en az 2 karakter olmalı.'
    kok = None
    if klasor:
        kok, hata = coz(klasor, dizin_ok=True)
        if hata:
            return hata
        if not kok.is_dir():
            return 'Hata: klasör değil.'
    try:
        rx = re.compile(desen if regex else re.escape(desen), 0 if buyuk else re.I)
    except re.error as exc:
        return f'Hata: geçersiz desen ({exc}).'
    sonuc = []
    n = 0
    for p in _kod_dosyalari(kok):
        try:
            if p.stat().st_size > MAX_ARA_DOSYA_BOYUT:
                continue
            for i, ln in enumerate(_metin(p).splitlines(), 1):
                if rx.search(ln):
                    n += 1
                    if len(sonuc) < max(1, min(int(en_cok or 30), 60)):
                        sonuc.append(f'{_goreli(p)}:{i}: {ln.strip()[:170]}')
        except OSError:
            continue
    if not sonuc:
        return 'Eşleşme yok.'
    return _kes(gizle('\n'.join(sonuc) + (f'\n… toplam {n} eşleşme' if n > len(sonuc) else '')))


def _islev_bul(metin: str, ad: str) -> list[tuple[int, int]]:
    try:
        agac = ast.parse(metin)
    except (SyntaxError, ValueError):
        agac = None
    out = []
    if agac is not None:
        for n in ast.walk(agac):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == ad:
                out.append((n.lineno, getattr(n, 'end_lineno', n.lineno + 40)))
    else:
        sat = metin.splitlines()
        for i, ln in enumerate(sat, 1):
            m = re.match(r'(\s*)(?:async\s+)?def\s+' + re.escape(ad) + r'\b', ln)
            if m:
                ind = len(m.group(1)); j = i
                while j < len(sat) and (not sat[j].strip() or len(sat[j]) - len(sat[j].lstrip()) > ind):
                    j += 1
                out.append((i, j))
    return out


def islev(dosya: str, ad: str) -> str:
    yol, hata = coz(dosya)
    if hata:
        return hata
    metin = _metin(yol)
    ad = str(ad or '').strip()
    if not re.fullmatch(r'[A-Za-z_]\w*', ad):
        return 'Hata: işlev adı geçersiz.'
    bul = _islev_bul(metin, ad)
    if not bul:
        return f'{_goreli(yol)} içinde "{ad}" adlı işlev yok.'
    sat = metin.splitlines()
    parca = []
    for b, e in bul[:2]:
        e = min(e, b + 79)
        parca.append(f'{_goreli(yol)}  {ad}  [{b}-{e}]\n' + '\n'.join(f'{i:>5}  {sat[i - 1]}' for i in range(b, e + 1)))
    return _kes(gizle('\n\n'.join(parca)))


# --------------------------------------------------------------------------- günlük + hata eşleştirme
_ZAMAN = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$')
_HATA = re.compile(r'(Traceback|Error\b|Exception\b|hata|başarısız|yüklenemedi|çöktü|zaman aşımı|failed|çıkarımı|kapatılıyor)', re.I)
_KARE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def _gunluk_satirlari() -> list[str]:
    out: list[str] = []
    for y in _gunluk_yollari():
        try:
            with y.open('rb') as fh:
                fh.seek(0, os.SEEK_END)
                n = fh.tell()
                fh.seek(max(0, n - GUNLUK_KUYRUK))
                out += fh.read().decode('utf-8', errors='replace').splitlines()
        except OSError:
            continue
    return out


def _imza(t: str) -> str:
    t = re.sub(r'0x[0-9a-fA-F]+', '0x#', t)
    t = re.sub(r'\d+', '#', t)
    t = re.sub(r'[A-Za-z]:\\[^\s"\']+', '<yol>', t)
    return t.strip()[:160]


def gunluk(adet: int = 40, filtre: str = '') -> str:
    sat = _gunluk_satirlari()
    if not sat:
        return 'Günlük dosyası yok ya da boş.'
    if filtre:
        f = str(filtre).lower()
        sat = [s for s in sat if f in s.lower()]
    adet = max(5, min(int(adet or 40), 120))
    return _kes(gizle('GÜNLÜK (son satırlar)\n' + '\n'.join(s[:240] for s in sat[-adet:])))


def hatalari_topla(saat: float = 72.0) -> list[dict]:
    sat = _gunluk_satirlari()
    sinir = time.time() - saat * 3600
    gruplar: dict[str, dict] = {}
    i = 0
    while i < len(sat):
        m = _ZAMAN.match(sat[i])
        if not m:
            i += 1
            continue
        zt, ileti = m.group(1), m.group(2)
        try:
            ts = time.mktime(time.strptime(zt, '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            ts = 0
        if ts and ts < sinir:
            i += 1
            continue
        kareler: list[tuple[str, int, str]] = []
        if 'Traceback (most recent call last)' in ileti or ileti.startswith('Traceback'):
            j = i + 1
            while j < len(sat) and not _ZAMAN.match(sat[j]):
                km = _KARE.search(sat[j])
                if km:
                    kareler.append((km.group(1), int(km.group(2)), km.group(3)))
                j += 1
            son = next((sat[k].strip() for k in range(j - 1, i, -1) if sat[k].strip() and not sat[k].startswith(' ')), ileti)
            anahtar, metin = _imza(son), son
            i = j
        elif _HATA.search(ileti):
            anahtar, metin = _imza(ileti), ileti
            i += 1
        else:
            i += 1
            continue
        g = gruplar.setdefault(anahtar, {'imza': anahtar, 'ornek': metin[:220], 'adet': 0, 'ilk': zt, 'son': zt, 'kareler': kareler})
        g['adet'] += 1
        g['son'] = zt
        if kareler:
            g['kareler'] = kareler
    return sorted(gruplar.values(), key=lambda g: (g['son'], g['adet']), reverse=True)


def _kaynak_dosya_bul(kare_yol: str) -> Path | None:
    k = kaynak_koku()
    if not k:
        return None
    y = kare_yol.replace('\\', '/')
    i = y.rfind('jarvis/')
    if i < 0:
        return None
    p = (k / y[i:]).resolve()
    return p if p.is_file() and _icinde(k, p) else None


def _anchorlar(ileti: str) -> list[str]:
    """Günlük metninden kaynakta aranabilecek SABİT parçalar (değişken kısımlar kırpılır), uzundan kısaya."""
    m = re.sub(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ', '', ileti)
    m = re.sub(r'^\w+: ', '', m)                  # "ek: " gibi etiketi at
    m = re.split(r'[\d{(\[\'"]|: ', m, maxsplit=1)[0].strip()
    adaylar = [m[:60], m.split(',')[0].strip(), ' '.join(m.split()[:3])]
    out = []
    for a in adaylar:
        a = re.sub(r'\s+\w*(?:Error|Exception)$', '', a).strip()
        if len(a) >= 8 and a not in out:
            out.append(a)
    return out


def hatalar(adet: int = 6, saat: float = 72.0) -> str:
    gr = hatalari_topla(float(saat or 72))
    if not gr:
        return f'Son {int(saat or 72)} saatte günlükte hata/uyarı satırı yok (ya da günlük bulunamadı).'
    cikti = [f'SON {int(saat or 72)} SAATTE {len(gr)} FARKLI HATA/UYARI (en yeniden eskiye):']
    for n, g in enumerate(gr[:max(1, min(int(adet or 6), 12))], 1):
        cikti.append(f'\n#{n} ×{g["adet"]}  son: {g["son"]}\n   {gizle(g["ornek"])}')
        gosterildi = False
        for yol, satir, ad in reversed(g['kareler']):
            kd = _kaynak_dosya_bul(yol)
            if kd and not gosterildi:
                cikti.append(f'   çağrı yığınında: {_goreli(kd)} (günlükte satır {satir}) işlev {ad}')
                bul = _islev_bul(_metin(kd), ad)
                if bul:
                    b, e = bul[0]
                    sat = _metin(kd).splitlines()
                    e = min(e, b + 24)
                    cikti.append(gizle('\n'.join(f'   {i:>5}  {sat[i - 1]}' for i in range(b, e + 1))))
                gosterildi = True
        if not gosterildi and not g['kareler']:
            for a in _anchorlar(g['ornek']):
                es = ara(a, 'jarvis', False, False, 3)
                if not es.startswith(('Eşleşme yok', 'Hata')):
                    cikti.append('   günlük metninin kaynakta geçtiği yer:\n' + '\n'.join('   ' + x for x in es.splitlines()[:3]))
                    break
    cikti.append('\nSonraki adım: ilgili dosyayı oku/islev ile aç, nedenini açıkla, düzeltmeyi yama_oner ile öner (kendin uygulayamazsın).')
    return _kes('\n'.join(cikti))


# --------------------------------------------------------------------------- yama önerisi (yazma YOK: yalnızca öneri dosyası)
def _oneri_klasoru() -> Path:
    from . import paths
    return Path(paths.DATA_DIR) / 'ek' / 'yama-onerileri'


def oneriler() -> list[Path]:
    try:
        return sorted(_oneri_klasoru().glob('*.md'))
    except OSError:
        return []


def yama_oner(baslik: str, dosya: str, eski: str, yeni: str, neden: str = '') -> str:
    baslik = ' '.join(str(baslik or '').split())[:100]
    if len(baslik) < 4:
        return 'Hata: öneriye kısa bir başlık yaz.'
    yol, hata = coz(dosya)
    if hata:
        return hata
    eski, yeni = str(eski or ''), str(yeni if yeni is not None else '')
    if not eski.strip():
        return 'Hata: "eski" (değişecek tam metin) boş olamaz.'
    metin = _metin(yol)
    adet = metin.count(eski)
    if adet != 1:
        return f'Hata: "eski" metin dosyada {adet} kez geçiyor; tam olarak 1 kez geçen, biraz daha uzun bir parça ver.'
    yeni_metin = metin.replace(eski, yeni, 1)
    uyari = ''
    if yol.suffix.lower() == '.py':
        try:
            ast.parse(yeni_metin)
        except SyntaxError as exc:
            return f'Hata: önerilen değişiklik Python sözdizimi hatası veriyor (satır {exc.lineno}: {exc.msg}); düzeltip tekrar dene.'
    elif yol.suffix.lower() == '.js':
        uyari = 'JS sözdizimi burada denetlenemedi.'
    diff = ''.join(difflib.unified_diff(metin.splitlines(True), yeni_metin.splitlines(True), f'a/{_goreli(yol)}', f'b/{_goreli(yol)}', n=3))
    if not diff:
        return 'Hata: değişiklik yok (eski ve yeni aynı).'
    ad = _goreli(yol)
    uygula = ('HUD dosyası: exe dışındaki dosyadır; yedeğini alıp elle (ya da Hermes ile) uygulanabilir.' if ad.startswith('hud/') else
              'Bu kaynak kopyadır; çalışan exe bayt kodudur. Uygulamak için kaynakta değiştirip YENİDEN DERLEMEK gerekir (kaynak projesinde araclar/insa.py).')
    kayit = (f'# Yama önerisi: {baslik}\n\nDosya: `{ad}`\nTarih: {time.strftime("%Y-%m-%d %H:%M")}\nDURUM: ÖNERİ — uygulanmadı.\n\n'
             f'## Neden\n{gizle(neden) or "(belirtilmedi)"}\n\n## Nasıl uygulanır\n{uygula}\n{uyari}\n\n## Değişiklik\n```diff\n{gizle(diff)}\n```\n')
    try:
        k = _oneri_klasoru()
        k.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r'[^a-z0-9]+', '-', baslik.lower().replace('ı', 'i').replace('ş', 's').replace('ğ', 'g').replace('ü', 'u').replace('ö', 'o').replace('ç', 'c')).strip('-')[:40] or 'oneri'
        p = k / f'{time.strftime("%Y%m%d-%H%M%S")}-{slug}.md'
        p.write_text(kayit, 'utf-8')
        for eski_p in oneriler()[:-MAX_ONERI]:
            try:
                eski_p.unlink()
            except OSError:
                pass
    except OSError as exc:
        return f'Hata: öneri yazılamadı ({type(exc).__name__}).'
    log('ek: yama önerisi yazıldı', p.name)
    return (f'Öneri kaydedildi (UYGULANMADI): {p.name}\nKonum: ek/yama-onerileri/ (veri klasörün içinde).\n{uygula}\n'
            f'Özet diff:\n{_kes(gizle(diff), 1800)}\nKullanıcıya ne bulduğunu ve neyi önerdiğini kısaca söyle; isterse gelisim(hermese_ver) ile Hermes\'e uygulatabilirsin (önizleme + onay).')


def oneri_listesi() -> str:
    o = oneriler()
    if not o:
        return 'Kayıtlı yama önerisi yok.'
    return 'Yama önerileri (ek/yama-onerileri/):\n' + '\n'.join(f'- {p.name}' for p in o[-15:])


# --------------------------------------------------------------------------- araç + istem
def istem_blogu() -> str:
    if izinli():
        return ('[KENDİ KODUN]\nKendi kaynak kodunu ve günlüğünü okuyabilirsin (izin AÇIK): "erişimim yok / kaynak kodum yok" DEME. '
                'Bir şey bozuksa/hata varsa: kendi_kod(hatalar), sonra oku/ara/islev. Düzeltmeyi yama_oner ile ÖNER (salt okunur; kendin uygulayamazsın).')
    return ('[KENDİ KODUN]\nKendi koduna bakabilirsin ama izin şu an KAPALI. "Erişimim yok / kaynak kodum yok" DEME. Kullanıcı kodunu/hatalarını '
            'incelemeni isterse ya da izin verdiğini söylerse HEMEN kendi_kod(izin_ver, kullanici_dedi=true) çağırıp işe başla; sormadan, kendiliğinden açma.')


def arac(a, _c=None) -> str:
    a = a or {}
    e = str(a.get('eylem') or 'durum').lower()
    if e == 'durum':
        d = durum()
        return (f'Kendi koduma okuma izni: {"VAR" if d["izin"] else "YOK"}. Kaynak klasörü: {"bulundu" if d["kaynak"] else "bulunamadı (bloom-kaynak exe\'nin yanında olmalı)"}; '
                f'HUD dosyaları: {"var" if d["hud"] else "yok"}; günlük: {"var" if d["gunluk"] else "yok"}; yama önerisi: {d["oneri"]}.')
    if e == 'izin_ver':
        if not a.get('kullanici_dedi'):
            return ('Kullanıcı kodunu/hatalarını incelemeni istedi ya da izin verdiğini söylediyse kullanici_dedi=true ile tekrar çağır ve işe başla. '
                    'İstemediyse kendiliğinden açma; "kendi koduma bakabilir miyim?" diye sor.')
        return izin_ayarla(True)
    if e == 'izin_kaldir':
        return izin_ayarla(False)
    g = _gerek()
    if g:
        return g
    try:
        if e == 'harita':
            return harita()
        if e == 'liste':
            return liste(a.get('klasor') or '')
        if e == 'oku':
            return oku(a.get('dosya'), a.get('baslangic') or 1, a.get('bitis'))
        if e == 'ara':
            return ara(a.get('desen'), a.get('klasor') or '', bool(a.get('regex')), bool(a.get('buyuk_kucuk')), a.get('en_cok') or 30)
        if e == 'islev':
            return islev(a.get('dosya'), a.get('ad'))
        if e == 'hatalar':
            return hatalar(a.get('adet') or 6, a.get('saat') or 72)
        if e == 'gunluk':
            return gunluk(a.get('adet') or 40, a.get('filtre') or '')
        if e == 'yama_oner':
            return yama_oner(a.get('baslik'), a.get('dosya'), a.get('eski'), a.get('yeni'), a.get('neden') or '')
        if e == 'oneriler':
            return oneri_listesi()
    except Exception as exc:
        log('ek: kendi_kod hatası', e, type(exc).__name__, str(exc)[:120])
        return f'Hata: {e} çalışmadı ({type(exc).__name__}).'
    return 'Hata: bilinmeyen eylem. durum | izin_ver | izin_kaldir | harita | liste | oku | ara | islev | hatalar | gunluk | yama_oner | oneriler.'
