"""BLOOM — kod yazma yetkinliği: dosyaları güvenle yazar, Visual Studio Code'u açar, denetler, düzenler; büyük projeleri arka planda üretir.

Neden ayrı bir araç: sesli model uzun kodu araç argümanı olarak yazarken kısalıyor/bozuluyor ve hiçbir yere kaydedemiyordu. Artık:

  yaz        küçük/orta kod: dosyaları proje klasörüne yazar, sözdizimini denetler, VS Code'u açar
  proje      BÜYÜK iş: arka planda (çoklu görev) plan → dosya dosya yazma → sözdizimi denetimi → hata varsa otomatik onarım → VS Code'u aç → bildir.
             Limit (429) olursa bekleyip dener; yarım kalırsa kaldığı yerden sürer (isler eylem=devam)
  duzenle    var olan dosyada tam eşleşen bir parçayı değiştirir (yedek alır)
  oku · liste · ac (VS Code) · kontrol (sözdizimi) · calistir (YALNIZCA kullanıcı onayıyla)

Güvenlik: yalnızca `Belgelerim/JARVIS-Kod/<proje>` altına yazar; mutlak yol, `..`, sürücü harfi, yürütülebilir uzantılar reddedilir; üzerine yazılan
dosyanın eski hali `.jarvis-yedek/` içinde kalır; kod ancak kullanıcı onayı (onay=true) ile ve zaman sınırıyla çalıştırılır.
"""

from __future__ import annotations
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from .log import log

KOK = os.environ.get('JARVIS_KOD_KLASORU') or str(Path.home() / 'Documents' / 'JARVIS-Kod')
MAX_DOSYA = 60
MAX_BOYUT = 400_000
MAX_PLAN_DOSYA = 12
YASAK_UZANTI = {'.exe', '.dll', '.scr', '.msi', '.lnk', '.com', '.sys', '.pif', '.reg', '.jar', '.app', '.dmg', '.cpl', '.msc'}
ADLAR_YASAK = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
CALISTIR_SN = 20
_BASLAT = subprocess.Popen      # testte değiştirilebilir
_L = threading.RLock()


def _ek():
    from . import ek
    return ek


def _fold(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or '').replace('İ', 'i').replace('I', 'ı').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if not unicodedata.combining(c)).replace('ı', 'i')).strip()


# --------------------------------------------------------------------------- yol güvenliği
def proje_adi(ad: str) -> str:
    s = re.sub(r'[^\w\- ]+', '', str(ad or ''), flags=re.U).strip().replace(' ', '-')
    s = re.sub(r'-{2,}', '-', s).strip('-._')[:50]
    if not s or s.lower() in ADLAR_YASAK:
        s = 'proje-' + dt.datetime.now().strftime('%Y%m%d-%H%M')
    return s


def proje_klasoru(ad: str) -> Path:
    return Path(KOK) / proje_adi(ad)


def guvenli_yol(klasor: Path, goreli: str) -> Path:
    """Proje klasörünün DIŞINA çıkamayan yol. Geçersizse ValueError."""
    g = str(goreli or '').strip().replace('\\', '/')
    g = re.sub(r'^\./+', '', g)
    if not g or g.endswith('/'):
        raise ValueError('Dosya adı boş.')
    if g.startswith('/') or re.match(r'^[A-Za-z]:', g) or g.startswith('~'):
        raise ValueError(f'“{goreli}”: yol proje klasörüne göreli olmalı (ör. src/main.py).')
    parcalar = g.split('/')
    if len(parcalar) > 7:
        raise ValueError(f'“{goreli}”: klasör derinliği çok fazla.')
    for p in parcalar:
        if p in ('', '.', '..') or p.endswith('.') or p.endswith(' ') or re.search(r'[<>:"|?*\x00-\x1f]', p):
            raise ValueError(f'“{goreli}”: geçersiz yol parçası “{p}”.')
        if p.split('.')[0].lower() in ADLAR_YASAK:
            raise ValueError(f'“{goreli}”: Windows’ta ayrılmış ad “{p}”.')
        if p.lower() == '.jarvis-yedek':
            raise ValueError('Yedek klasörüne yazılamaz.')
    if os.path.splitext(parcalar[-1])[1].lower() in YASAK_UZANTI:
        raise ValueError(f'“{goreli}”: bu dosya türünü (yürütülebilir) yazmıyorum.')
    hedef = (klasor / g).resolve()
    if klasor.resolve() not in hedef.parents:
        raise ValueError(f'“{goreli}” proje klasörünün dışına çıkıyor.')
    return hedef


# --------------------------------------------------------------------------- dosya ayrıştırma
def _kod_cit_temizle(t: str) -> str:
    t = str(t or '').replace('\r\n', '\n')
    m = re.match(r'^\s*```[\w+\-.#]*\n(.*?)\n?```\s*$', t, re.S)
    if m:
        return m.group(1)
    return t


def dosyalari_ayir(metin: str) -> dict:
    """\"### dosya: yol\\n<içerik>\" bloklarını ya da {\"dosyalar\":[{\"yol\",\"icerik\"}]} JSON'unu {yol: içerik} yapar. Sıra korunur."""
    ham = str(metin or '')
    out: dict[str, str] = {}
    if ham.lstrip().startswith(('{', '[')):
        try:
            d = json.loads(ham)
            liste = d.get('dosyalar') if isinstance(d, dict) else d
            for e in liste or []:
                y, i = str(e.get('yol') or e.get('dosya') or ''), e.get('icerik') if e.get('icerik') is not None else e.get('kod')
                if y and i is not None:
                    out[y.strip()] = str(i)
            if out:
                return out
        except Exception:
            pass
    parcalar = re.split(r'(?m)^[ \t]*(?:#{2,4}|={3,})[ \t]*(?:dosya|file)[ \t]*:[ \t]*(.+?)[ \t]*(?:={3,})?[ \t]*$', ham, flags=re.I)
    for i in range(1, len(parcalar) - 1, 2):
        yol = parcalar[i].strip().strip('`').strip()
        icerik = _kod_cit_temizle(parcalar[i + 1].strip('\n'))
        if yol:
            out[yol] = icerik if icerik.endswith('\n') or not icerik else icerik + '\n'
    return out


# --------------------------------------------------------------------------- yazma
def _atomik_yaz(yol: Path, icerik: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + '.jarvis-tmp')
    with open(gecici, 'w', encoding='utf-8', newline='\n') as f:
        f.write(icerik)
    os.replace(gecici, yol)


def _yedekle(klasor: Path, yol: Path) -> None:
    try:
        if yol.is_file():
            h = klasor / '.jarvis-yedek'
            h.mkdir(exist_ok=True)
            shutil.copy2(yol, h / f'{yol.name}.{dt.datetime.now().strftime("%Y%m%d-%H%M%S")}.bak')
            eski = sorted(h.glob('*.bak'), key=lambda p: p.stat().st_mtime)
            for p in eski[:-60]:
                p.unlink(missing_ok=True)
    except Exception as exc:
        log('ek_kod: yedek alınamadı', type(exc).__name__, str(exc)[:80])


def yaz(proje: str, dosyalar: dict) -> dict:
    """{'klasor','yazilan':[(yol,bayt,'yeni'|'değişti'|'aynı')]}. Hepsi doğrulanmadan hiçbiri yazılmaz."""
    if not dosyalar:
        raise ValueError('Yazılacak dosya yok.')
    if len(dosyalar) > MAX_DOSYA:
        raise ValueError(f'Bir seferde en çok {MAX_DOSYA} dosya.')
    klasor = proje_klasoru(proje)
    hedefler = []
    for yol, icerik in dosyalar.items():
        h = guvenli_yol(klasor, yol)
        if len(str(icerik).encode('utf-8')) > MAX_BOYUT:
            raise ValueError(f'“{yol}” çok büyük (en çok {MAX_BOYUT // 1000} KB).')
        hedefler.append((yol, h, str(icerik)))
    klasor.mkdir(parents=True, exist_ok=True)
    sonuc = []
    with _L:
        for yol, h, icerik in hedefler:
            eski = h.read_text(encoding='utf-8', errors='replace') if h.is_file() else None
            durum = 'yeni' if eski is None else ('aynı' if eski == icerik else 'değişti')
            if durum == 'değişti':
                _yedekle(klasor, h)
            if durum != 'aynı':
                _atomik_yaz(h, icerik)
            sonuc.append((yol.replace('\\', '/'), len(icerik.encode('utf-8')), durum))
    return {'klasor': str(klasor), 'yazilan': sonuc}


# --------------------------------------------------------------------------- sözdizimi denetimi
def _atla(p: Path, klasor: Path) -> bool:
    return any(x in ('.jarvis-yedek', 'node_modules', '.git', '__pycache__', '.venv', 'venv') for x in p.relative_to(klasor).parts)


def dosya_denetle(yol: Path, icerik: str | None = None) -> str | None:
    """Hata varsa tek satır açıklama, yoksa None."""
    ek = yol.suffix.lower()
    try:
        kaynak = icerik if icerik is not None else yol.read_text(encoding='utf-8', errors='replace')
        if ek == '.py':
            compile(kaynak, str(yol.name), 'exec')
        elif ek == '.json':
            json.loads(kaynak)
        elif ek in ('.js', '.mjs', '.cjs'):
            node = shutil.which('node')
            if node:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    gec = Path(td) / ('chk' + ek)
                    gec.write_text(kaynak, encoding='utf-8')
                    r = subprocess.run([node, '--check', str(gec)], capture_output=True, text=True, timeout=10)
                if r.returncode != 0:
                    ilk = [s for s in (r.stderr or '').splitlines() if s.strip()]
                    return f'{yol.name}: ' + (next((s for s in ilk if 'Error' in s), ilk[0] if ilk else 'sözdizimi hatası'))[:160]
        elif ek in ('.html', '.htm'):
            ac_, kap = len(re.findall(r'<script\b', kaynak, re.I)), len(re.findall(r'</script>', kaynak, re.I))
            if ac_ != kap:
                return f'{yol.name}: <script> etiketleri eşleşmiyor ({ac_} açılış, {kap} kapanış)'
    except SyntaxError as exc:
        return f'{yol.name}: satır {exc.lineno}: {exc.msg}'
    except json.JSONDecodeError as exc:
        return f'{yol.name}: JSON hatası satır {exc.lineno}: {exc.msg}'
    except Exception as exc:
        return f'{yol.name}: denetlenemedi ({type(exc).__name__})'
    return None


def denetle(klasor: Path, yollar: list[str] | None = None) -> list[str]:
    hatalar = []
    adaylar = [klasor / y for y in yollar] if yollar else [p for p in sorted(klasor.rglob('*')) if p.is_file() and not _atla(p, klasor)]
    for p in adaylar[:300]:
        if p.is_file():
            h = dosya_denetle(p)
            if h:
                hatalar.append(h.replace(p.name + ':', str(p.relative_to(klasor)).replace('\\', '/') + ':', 1))
    return hatalar


# --------------------------------------------------------------------------- Visual Studio Code
def vscode_bul() -> str | None:
    """VS Code çalıştırılabilir yolu (Code.exe tercih edilir; `code` komutu yedek)."""
    adaylar = []
    if sys.platform == 'win32':
        for k in ('LOCALAPPDATA',):
            v = os.environ.get(k)
            if v:
                adaylar.append(os.path.join(v, 'Programs', 'Microsoft VS Code', 'Code.exe'))
        for k in ('ProgramFiles', 'ProgramFiles(x86)'):
            v = os.environ.get(k)
            if v:
                adaylar.append(os.path.join(v, 'Microsoft VS Code', 'Code.exe'))
        c = shutil.which('code.cmd') or shutil.which('code')
        if c:
            exe = os.path.normpath(os.path.join(os.path.dirname(c), '..', 'Code.exe'))
            adaylar.insert(0, exe)
            adaylar.append(c)
    else:
        c = shutil.which('code')
        if c:
            adaylar.append(c)
        adaylar += ['/usr/bin/code', '/usr/local/bin/code', '/snap/bin/code', '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code']
    env = os.environ.get('JARVIS_VSCODE')
    if env:
        adaylar.insert(0, env)
    for a in adaylar:
        if a and os.path.isfile(a):
            return a
    return None


def vscode_ac(klasor: Path, dosya: Path | None = None) -> tuple[bool, str]:
    """Klasörü (ve varsa bir dosyayı) VS Code'da açar. (açıldı_mı, açıklama). Bulunamazsa klasörü Gezgin'de açmayı dener."""
    exe = vscode_bul()
    if exe:
        try:
            args = [exe, str(klasor)] + (['-g', str(dosya)] if dosya else [])
            bayrak = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
            _BASLAT(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=bayrak) if sys.platform == 'win32' \
                else _BASLAT(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            return True, 'Visual Studio Code açıldı.'
        except Exception as exc:
            log('ek_kod: VS Code açılamadı', type(exc).__name__, str(exc)[:100])
    try:
        if sys.platform == 'win32' and hasattr(os, 'startfile'):
            os.startfile(str(klasor))        # noqa
            return False, 'Visual Studio Code bulunamadı; klasörü Dosya Gezgini’nde açtım (VS Code kurulu değilse code.visualstudio.com).'
    except Exception:
        pass
    return False, 'Visual Studio Code bulunamadı (kurulu değil ya da yolu bilinmiyor); dosyalar klasörde hazır.'


# --------------------------------------------------------------------------- okuma / listeleme / düzenleme
def _proje_bul(ad: str) -> Path | None:
    """Tam ya da kısmi ada göre proje klasörü; yoksa None. Ad boşsa en son değişen."""
    kok = Path(KOK)
    if not kok.is_dir():
        return None
    klasorler = [p for p in kok.iterdir() if p.is_dir()]
    if not klasorler:
        return None
    if not str(ad or '').strip():
        return max(klasorler, key=lambda p: p.stat().st_mtime)
    f = _fold(proje_adi(ad))
    for p in klasorler:
        if _fold(p.name) == f:
            return p
    uy = [p for p in klasorler if f in _fold(p.name) or _fold(p.name) in f]
    return uy[0] if len(uy) == 1 else None


def liste(proje: str = '') -> str:
    kok = Path(KOK)
    if not proje:
        if not kok.is_dir() or not any(p.is_dir() for p in kok.iterdir()):
            return f'Henüz proje yok (klasör: {KOK}).'
        ps = sorted((p for p in kok.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:15]
        return f'Projeler ({KOK}):\n' + '\n'.join(f'- {p.name} ({sum(1 for q in p.rglob("*") if q.is_file() and not _atla(q, p))} dosya)' for p in ps)
    p = _proje_bul(proje)
    if not p:
        return f'“{proje}” adlı proje yok.'
    dos = [q for q in sorted(p.rglob('*')) if q.is_file() and not _atla(q, p)]
    return f'{p.name} — {len(dos)} dosya:\n' + '\n'.join(f'- {q.relative_to(p).as_posix()} ({q.stat().st_size} bayt)' for q in dos[:80])


def oku(proje: str, dosya: str, sayfa: int = 1) -> str:
    p = _proje_bul(proje)
    if not p:
        return f'“{proje}” adlı proje yok (liste ile bak).'
    h = guvenli_yol(p, dosya)
    if not h.is_file():
        return f'“{dosya}” dosyası yok. ' + liste(p.name)
    t = h.read_text(encoding='utf-8', errors='replace')
    n = 6000
    toplam = max(1, -(-len(t) // n))
    sayfa = max(1, min(int(sayfa or 1), toplam))
    parca = t[(sayfa - 1) * n: sayfa * n]
    return f'{p.name}/{dosya} — {len(t)} karakter' + (f', sayfa {sayfa}/{toplam}' if toplam > 1 else '') + ':\n' + parca + (f'\n… (devamı için sayfa={sayfa + 1})' if sayfa < toplam else '')


def duzenle(proje: str, dosya: str, eski: str, yeni: str) -> str:
    """`eski` metni dosyada TAM BİR kez geçmeli (boşluklar dahil); `yeni` ile değiştirir."""
    p = _proje_bul(proje)
    if not p:
        return f'“{proje}” adlı proje yok.'
    h = guvenli_yol(p, dosya)
    if not h.is_file():
        return f'“{dosya}” dosyası yok.'
    if not str(eski or ''):
        return 'Değiştirilecek eski metin (eski) boş.'
    t = h.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    sayi = t.count(eski)
    if sayi == 0:
        # boşluk farkını tolere et: satır sonu boşlukları ve girinti
        norm = lambda x: '\n'.join(s.rstrip() for s in x.split('\n'))
        if norm(eski) in norm(t) and norm(t).count(norm(eski)) == 1:
            t_, e_ = norm(t), norm(eski)
            yeni_t = t_.replace(e_, yeni, 1)
        else:
            return 'Eski metin dosyada bulunamadı (boşluklar/girinti dahil birebir olmalı). Önce oku ile bak.'
    elif sayi > 1:
        return f'Eski metin dosyada {sayi} kez geçiyor; tek yer olacak kadar uzun/özgün bir parça ver.'
    else:
        yeni_t = t.replace(eski, str(yeni), 1)
    hata = dosya_denetle(h, yeni_t)
    _yedekle(p, h)
    _atomik_yaz(h, yeni_t)
    return f'{dosya} güncellendi.' + (f' Uyarı, değişiklikten sonra sözdizimi sorunu: {hata}' if hata else ' Sözdizimi temiz.')


# --------------------------------------------------------------------------- çalıştırma (yalnızca onayla)
def _yorumlayici(ek: str):
    if ek == '.py':
        for ad in ('python', 'python3', 'py'):
            x = shutil.which(ad)
            if x:
                return [x]
        return None
    if ek in ('.js', '.mjs', '.cjs'):
        x = shutil.which('node')
        return [x] if x else None
    return None


def calistir(proje: str, dosya: str, argumanlar: str = '', onay: bool = False) -> str:
    p = _proje_bul(proje)
    if not p:
        return f'“{proje}” adlı proje yok.'
    h = guvenli_yol(p, dosya)
    if not h.is_file():
        return f'“{dosya}” dosyası yok.'
    yor = _yorumlayici(h.suffix.lower())
    if yor is None:
        return f'{h.suffix} dosyaları için çalıştırıcı yok ya da kurulu değil (yalnızca Python ve Node.js çalıştırırım). VS Code’da kendin çalıştırabilirsin.'
    if not onay:
        return (f'ÇALIŞTIRMADIM: kodu bilgisayarda çalıştırmak için kullanıcının onayı gerekir. Kullanıcıya sor: “{p.name}/{dosya} dosyasını çalıştırayım mı?” '
                f'Evet derse calistir islemini onay=true ile yeniden çağır ({CALISTIR_SN} sn sınırı var).')
    try:
        r = subprocess.run(yor + [str(h)] + [x for x in str(argumanlar or '').split()][:10], cwd=str(p), capture_output=True, text=True,
                           timeout=CALISTIR_SN, stdin=subprocess.DEVNULL, errors='replace')
    except subprocess.TimeoutExpired as exc:
        cikti = ((exc.stdout or b'').decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''))
        return f'{CALISTIR_SN} sn içinde bitmedi, durdurdum (sonsuz döngü/bekleme olabilir; girdi bekleyen programlar burada çalışmaz).\nÇıktı:\n{cikti[-1500:]}'
    cikti = (r.stdout or '')[-2500:]
    hata = (r.stderr or '')[-1800:]
    return f'Çıkış kodu {r.returncode}.' + (f'\nÇIKTI:\n{cikti}' if cikti.strip() else '\n(çıktı yok)') + (f'\nHATA:\n{hata}' if hata.strip() else '')


# --------------------------------------------------------------------------- araç
def _ozet_yazilan(s: dict) -> str:
    y = s['yazilan']
    return f'{len(y)} dosya (' + ', '.join(f'{a} {c}' for a, _, c in y[:8]) + ('…' if len(y) > 8 else '') + ')'


def arac_yaz(a: dict) -> str:
    proje = str(a.get('proje') or '').strip()
    dos = dosyalari_ayir(str(a.get('dosyalar') or ''))
    if not dos and a.get('dosya') and a.get('icerik') is not None:
        dos = {str(a['dosya']).strip(): _temiz_icerik(str(a['icerik']))}
    if not dos:
        return ('Dosya içeriği gelmedi. Biçim: dosya=src/main.py ve icerik=<kod> VEYA dosyalar="### dosya: main.py\\n<kod>\\n### dosya: util.py\\n<kod>". '
                'Çok büyük/çok dosyalı işlerde yaz yerine proje islemini kullan.')
    s = yaz(proje, dos)
    klasor = Path(s['klasor'])
    hatalar = denetle(klasor, [y for y, _, c in s['yazilan'] if c != 'aynı'])
    ac_ok, ac_msg = (False, '')
    if a.get('ac_vscode') is not False:
        ilk = guvenli_yol(klasor, s['yazilan'][0][0])
        ac_ok, ac_msg = vscode_ac(klasor, ilk)
    return (f'Yazıldı: {klasor} — {_ozet_yazilan(s)}. ' + (ac_msg + ' ' if ac_msg else '') +
            ('SÖZDİZİMİ SORUNLARI: ' + ' | '.join(hatalar[:6]) + ' — bunları duzenle ile düzelt ve kullanıcıya söyle.' if hatalar else 'Sözdizimi denetimi temiz.') +
            ' Kullanıcıya kısaca ne yazdığını ve nerede olduğunu söyle; kodu sesli OKUMA.')


def arac(a: dict, _c=None) -> str:
    a = a or {}
    islem = _fold(a.get('islem') or 'yaz')
    try:
        if islem == 'yaz':
            return arac_yaz(a)
        if islem == 'proje':
            return proje_baslat(a)
        if islem == 'liste':
            return liste(str(a.get('proje') or ''))
        if islem == 'oku':
            return oku(str(a.get('proje') or ''), str(a.get('dosya') or ''), int(a.get('sayfa') or 1))
        if islem == 'duzenle':
            return duzenle(str(a.get('proje') or ''), str(a.get('dosya') or ''), str(a.get('eski') or ''), str(a.get('yeni') if a.get('yeni') is not None else ''))
        if islem == 'kontrol':
            p = _proje_bul(str(a.get('proje') or ''))
            if not p:
                return 'Böyle bir proje yok.'
            h = denetle(p)
            return f'{p.name}: ' + ('sözdizimi sorunları: ' + ' | '.join(h[:10]) if h else 'sözdizimi denetimi temiz (Python/JSON/JS/HTML).')
        if islem == 'ac':
            p = _proje_bul(str(a.get('proje') or ''))
            if not p:
                return 'Böyle bir proje yok (liste ile bak).'
            d = guvenli_yol(p, str(a['dosya'])) if a.get('dosya') else None
            ok, msg = vscode_ac(p, d if d and d.is_file() else None)
            return f'{p.name}: {msg}'
        if islem == 'calistir':
            return calistir(str(a.get('proje') or ''), str(a.get('dosya') or ''), str(a.get('argumanlar') or ''), bool(a.get('onay')))
        return 'Bilinmeyen kod işlemi. Geçerli: yaz, proje, duzenle, oku, liste, ac, kontrol, calistir.'
    except ValueError as exc:
        return f'Kod işlemi yapılamadı: {exc}'
    except Exception as exc:
        log('ek_kod: işlem hatası', islem, type(exc).__name__, str(exc)[:120])
        return f'Kod işlemi başarısız ({type(exc).__name__}).'


def istem_blogu() -> str:
    return '[KOD] kod aracı (küçük: yaz, büyük: proje); VS Code açılır; çalıştırmadan önce onay al.'


# --------------------------------------------------------------------------- arka plan proje hattı
PLAN_TALIMAT = ('Sen kıdemli bir yazılım mimarısın. Kullanıcının isteği için KÜÇÜK ama TAM çalışan bir proje planla. Yalnızca JSON döndür: '
                '{{"proje":"kisa-klasor-adi","aciklama":"1-2 cümle","dil":"python|javascript|html|diğer","calistir":"nasıl çalıştırılır (tek satır)",'
                '"dosyalar":[{{"yol":"main.py","amac":"bu dosyanın sorumluluğu ve diğer dosyalarla arayüzü (işlev/sınıf adları)"}}]}}. '
                'En çok {n} dosya; mümkünse az dosya. Dış kütüphane gerekiyorsa requirements.txt/package.json ekle ve README.md koy. Yollar göreli, ASCII, klasör derinliği ≤3. Tarih: {now}.')
DOSYA_TALIMAT = ('Sen deneyimli bir yazılım mühendisisin. Projenin TEK bir dosyasını TAM olarak yaz. Yalnızca dosyanın içeriğini döndür: açıklama, başlık ya da ``` çiti YOK. '
                 'Kod eksiksiz çalışmalı: yer tutucu, “TODO”, “buraya ekle” bırakma; plandaki diğer dosyalarla adları/imzaları birebir uyumlu olsun; '
                 'hataları yönet; kısa, yararlı yorumlar yaz (kullanıcı Türkçe, yorumlar Türkçe olabilir). Tarih: {now}.')
ONAR_TALIMAT = ('Aşağıdaki dosyada sözdizimi hatası var. Dosyanın DÜZELTİLMİŞ TAM içeriğini döndür; yalnızca içerik, açıklama ya da ``` çiti yok. Hatanın dışındaki davranışı değiştirme.')
README_SABLON = '# {baslik}\n\n{aciklama}\n\n## Çalıştırma\n\n{calistir}\n\n_BLOOM tarafından yazıldı, {tarih}._\n'


def _temiz_icerik(t: str) -> str:
    t = _kod_cit_temizle(str(t or '').strip('\n'))
    return t if t.endswith('\n') or not t else t + '\n'


def _json(raw):
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', str(raw or '').strip())
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


def _plan_yap(istek: str, ad: str, dene) -> dict:
    ek = _ek()
    simdi = dt.datetime.now().strftime('%d.%m.%Y')
    ham = dene(lambda: ek._uret_metin(PLAN_TALIMAT.format(n=MAX_PLAN_DOSYA, now=simdi), istek, json=True, max_token=2000, zaman_ms=40000), 'plan')
    d = _json(ham) or {}
    dos = []
    gor = set()
    for e in d.get('dosyalar') or []:
        y = str((e or {}).get('yol') or '').strip().replace('\\', '/')
        try:
            guvenli_yol(Path(KOK) / 'x', y)
        except ValueError:
            continue
        if y and y not in gor:
            gor.add(y)
            dos.append({'yol': y, 'amac': str((e or {}).get('amac') or '')[:300]})
    if not dos:
        raise RuntimeError('proje planı çıkarılamadı')
    return {'proje': proje_adi(ad or d.get('proje') or 'proje'), 'aciklama': str(d.get('aciklama') or istek)[:300], 'calistir': str(d.get('calistir') or '')[:200],
            'dosyalar': dos[:MAX_PLAN_DOSYA]}


def _boru(is_kaydi: dict, istek: str) -> str:
    """İş parçacığında: plan → dosyalar → denetim/onarım → yazma → VS Code. Döner: tamamlama metni. Yarım kalırsa ek_arastir.Yarim fırlatır."""
    from . import ek_isler, ek_arastir as EA
    ek = _ek()
    is_id = is_kaydi['id']
    kontrol = is_kaydi.setdefault('kontrol', {})
    iptal = lambda: ek_isler.iptal_istendi(is_id)

    def haber(m):
        ek_isler.guncelle(is_id, ilerleme=str(m)[:120])

    def dene(fn, etiket, toplam=240.0):
        return EA._dene(fn, toplam, iptal=iptal, haber=haber, etiket=etiket)

    def kaydet():
        ek_isler.kontrol_yaz(is_id, kontrol)
    simdi = dt.datetime.now().strftime('%d.%m.%Y')
    if 'plan' not in kontrol:
        haber('proje planlanıyor')
        try:
            kontrol['plan'] = _plan_yap(istek, str(is_kaydi['parametre'].get('proje') or ''), dene)
        except EA.Yarim:
            raise
        except (EA.Iptal,):
            raise
        except Exception as exc:
            if EA.hata_turu(exc) in ('limit', 'gunluk', 'gecici'):
                raise EA.Yarim(f'plan: {str(exc)[:80]}', None, EA.hata_turu(exc) == 'gunluk', 'plan')
            raise
        kontrol['yazilan'] = {}
        kaydet()
    plan = kontrol['plan']
    yazilan: dict = kontrol.setdefault('yazilan', {})
    dosyalar = plan['dosyalar']
    plan_metni = f'PROJE: {plan["proje"]}\nAÇIKLAMA: {plan["aciklama"]}\nİSTEK: {istek}\nDOSYALAR:\n' + '\n'.join(f'- {d["yol"]}: {d["amac"]}' for d in dosyalar)
    for i, d in enumerate(dosyalar, 1):
        if d['yol'] in yazilan:
            continue
        if iptal():
            raise EA.Iptal('iptal edildi')
        haber(f'{d["yol"]} yazılıyor ({i}/{len(dosyalar)})')
        onceki = '\n\n'.join(f'--- {y} (yazıldı) ---\n{c[:2500]}' for y, c in list(yazilan.items())[-4:])
        icerik_istem = f'{plan_metni}\n\n{onceki}\n\nŞİMDİ YAZILACAK DOSYA: {d["yol"]} — {d["amac"]}'
        try:
            ham = dene(lambda: ek._uret_metin(DOSYA_TALIMAT.format(now=simdi), icerik_istem, json=False, max_token=12000, zaman_ms=120000, sicaklik=0.2), d['yol'])
        except (EA.Iptal, EA.Yarim):
            raise
        except Exception as exc:
            tur = EA.hata_turu(exc)
            if tur in ('limit', 'gunluk', 'gecici'):
                raise EA.Yarim(f'{d["yol"]}: {str(exc)[:80]}', None, tur == 'gunluk', 'dosya')
            raise
        yazilan[d['yol']] = _temiz_icerik(ham)
        kaydet()
    # denetim + onarım (dosya başına en çok 2 deneme)
    for y, c in list(yazilan.items()):
        for deneme in range(3):
            hata = dosya_denetle(Path(y), c)       # yalnızca ad/uzantı için; dosya yazılmaz (icerik verildi)
            if not hata:
                break
            if deneme == 2 or iptal():
                break
            haber(f'{y} onarılıyor ({deneme + 1}/2)')
            try:
                c = _temiz_icerik(dene(lambda: ek._uret_metin(ONAR_TALIMAT, f'DOSYA: {y}\nHATA: {hata}\n\n{c}', json=False, max_token=12000, zaman_ms=120000, sicaklik=0.1), 'onar-' + y, 120.0))
                yazilan[y] = c
            except (EA.Iptal,):
                raise
            except Exception as exc:
                log('ek_kod: onarım başarısız', y, type(exc).__name__, str(exc)[:80])
                break
    if not any(Path(y).name.lower() == 'readme.md' for y in yazilan):
        yazilan['README.md'] = README_SABLON.format(baslik=plan['proje'], aciklama=plan['aciklama'], calistir=plan['calistir'] or 'Dosyalara bakın.', tarih=simdi)
    haber('dosyalar yazılıyor')
    s = yaz(plan['proje'], yazilan)
    klasor = Path(s['klasor'])
    kalan = denetle(klasor, [y for y, _, c in s['yazilan']])
    ilk = next((y for y, _, _ in s['yazilan'] if Path(y).suffix in ('.py', '.js', '.html')), s['yazilan'][0][0])
    ac_ok, ac_msg = vscode_ac(klasor, guvenli_yol(klasor, ilk))
    return (f'Kod projesi hazır: “{plan["proje"]}” — {_ozet_yazilan(s)}; klasör {klasor}. {ac_msg} ' +
            (f'Çalıştırma: {plan["calistir"]}. ' if plan['calistir'] else '') +
            ('KALAN SÖZDİZİMİ SORUNLARI (otomatik onarılamadı): ' + ' | '.join(kalan[:5]) + '. ' if kalan else 'Sözdizimi denetimi temiz. ') +
            'Kullanıcıya ne yazıldığını kısaca söyle; çalıştırmak için onayını sor.')


def _calistir_is(is_kaydi: dict, istek: str, arka: bool) -> None:
    from . import ek_isler, ek_arastir as EA
    is_id = is_kaydi['id']
    durum, cikti = 'bitti', ''
    try:
        cikti = _boru(is_kaydi, istek)
    except EA.Iptal:
        durum, cikti = 'iptal', 'Kod projesi kullanıcının isteğiyle iptal edildi.'
    except EA.Yarim as y:
        durum = 'yarim'
        n = len(is_kaydi.get('kontrol', {}).get('yazilan', {}))
        cikti = (f'Kod projesi yarım kaldı [{is_id}]: {y} ({n} dosya SAKLANDI). ' + ('Günlük kota dolmuş görünüyor; kota yenilenince ' if getattr(y, 'gunluk', False) else 'Limit dolu; birazdan ') +
                 'isler(eylem=devam) ile kaldığı yerden tamamlanır. Kullanıcıya dürüstçe söyle.')
    except Exception as exc:
        durum = 'hata'
        log('ek_kod: proje hattı başarısız', type(exc).__name__, str(exc)[:160])
        cikti = f'Hata: kod projesi yazılamadı ({type(exc).__name__}: {str(exc)[:100]}). Kullanıcıya dürüstçe söyle.'
    ek_isler.bitir(is_id, durum, cikti[:600], {'bitti': 'tamamlandı', 'yarim': 'yarım — dosyalar saklı', 'iptal': 'iptal edildi', 'hata': 'hata'}[durum])
    ek_isler.teslim_et('kod:' + is_id, '[KOD PROJESİ] ' + cikti)


def proje_baslat(a: dict, devam: dict | None = None) -> str:
    from . import ek_isler
    if devam is not None:
        k = devam
        istek = str(k['parametre'].get('istek') or '')
        ek_isler.guncelle(k['id'], durum='calisiyor', ilerleme='kaldığı yerden sürdürülüyor')
    else:
        istek = ' '.join(str(a.get('istek') or a.get('metin') or '').split())
        if len(istek) < 12:
            return 'Ne yazmamı istediğini biraz daha ayrıntılı anlat (istek).'
        for k in ek_isler.aktifler('kod'):
            if k.get('parametre', {}).get('istek') == istek:
                return f'Bu kod projesi zaten yazılıyor [{k["id"]}] ({k.get("ilerleme", "")}). Bitince ben haber veririm.'
        try:
            k = ek_isler.yeni('kod', istek[:70], {'istek': istek, 'proje': str(a.get('proje') or '')})
        except ek_isler.Dolu as exc:
            return f'Hata: {exc} Kullanıcıya söyle.'
    threading.Thread(target=_calistir_is, args=(k, istek, True), daemon=True, name='ek-kod').start()
    return (f'Kod projesi [{k["id"]}] arka planda yazılıyor: önce plan, sonra dosya dosya, sözdizimi denetimi ve gerekirse otomatik onarım; bitince Visual Studio Code açılır ve sana haber veririm. '
            'Limit olursa beklenip yeniden denenir. Kullanıcıya tek cümleyle söyle; bu sırada başka konuşabilirsiniz (durum: isler aracı).')


def devam(k: dict, a: dict) -> str:
    return proje_baslat(a or {}, devam=k)
