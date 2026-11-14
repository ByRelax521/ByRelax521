"""BLOOM EK — Fikir Alanım, BLOOM'un içinde.

* Fikir Alanım'ın dosyaları bu exe'nin içinde gömülüdür (ek_fikir_dosya). Yalnızca bu bilgisayarda (127.0.0.1) çalışan küçük bir
  hizmet onları sunar ve verileri `%APPDATA%\\JARVIS V4\\fikir-veri.json` dosyasında saklar (eski Fikir sürümüyle aynı dosya/biçim).
* BLOOM'un yapay zekâsı ve anımsatıcılar/takvim aynı veriyi doğrudan okur-yazar. Fikir sayfası eski sürümle kaydetmeye
  kalkarsa hizmet 409 döner ve sayfa kendini tazeler (yapay zekânın değişikliği ezilmez).
* Anımsatıcı = Fikir görevi (+ isteğe bağlı saat). Takvim = yerel takvim + Fikir haftalık programı.
* "Gizli" (aiHidden) kategorideki görev/fikirleri yapay zekâ GÖRMEZ.
"""

from __future__ import annotations
import base64
import datetime as dt
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import paths
from .log import log

PORT = 47833
KEY_TASKS = 'panel.v3.tasks'
KEY_CATS = 'panel.v3.cats'
KEY_BOARD = 'fikir.workspace.v5'
KEY_TRASH = 'fikir.recycle.v1'
KEY_WEEK = 'fikir.week.v1'
TR_GUN = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
TR_GUN_ASCII = ['pazartesi', 'sali', 'carsamba', 'persembe', 'cuma', 'cumartesi', 'pazar']
RENKLER = {'focus', 'meeting', 'personal', 'health', 'admin', 'rest'}
ONCELIK = {'normal': 0, 'important': 5, 'high': 1}
SAAT_RE = re.compile(r'(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])')

_L = threading.RLock()
_F = {'port': 0, 'srv': None, 'epoch': int(time.time()) % 1000000000, 'dosyalar': None, 'izleyici': False, 'onceki': {}}


def _ek():
    from . import ek
    return ek


# --------------------------------------------------------------------------- dosya
def veri_yolu():
    return paths.DATA_DIR / 'fikir-veri.json'


def _yedek_dizini():
    d = paths.DATA_DIR / 'fikir-yedek'
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def snapshot_oku() -> dict:
    """{'v':1,'savedAt':ms,'items':{anahtar: json metni}}; bozuksa kenara alır, boş döner."""
    try:
        from . import ek_yayin as _Y          # yayın modu: gerçek veri okunmaz, bellekteki DEMO verisi döner
        if _Y.kat('fikir'):
            return _Y.fikir_oku()
    except Exception:
        pass
    p = veri_yolu()
    try:
        raw = p.read_text('utf-8')
    except FileNotFoundError:
        return {'v': 1, 'savedAt': 0, 'items': {}}
    except OSError:
        # Windows'ta antivirüs/yedekleme dosyayı anlık kilitleyebilir: BOŞ dönersek bir sonraki kayıt tüm veriyi ezerdi → yeniden dene, olmazsa hata ver.
        raw = None
        son = None
        for _ in range(8):
            time.sleep(0.12)
            try:
                raw = p.read_text('utf-8')
                break
            except FileNotFoundError:
                return {'v': 1, 'savedAt': 0, 'items': {}}
            except OSError as exc:
                son = exc
        if raw is None:
            log('ek_fikir: veri okunamadı', son)
            raise son
    try:
        d = json.loads(raw)
        items = d.get('items')
        if not isinstance(items, dict):
            raise ValueError('items yok')
        return {'v': 1, 'savedAt': d.get('savedAt', 0), 'items': {str(k): str(v) for k, v in items.items()}}
    except Exception as exc:
        try:
            p.replace(p.with_name('fikir-veri.bozuk-' + time.strftime('%Y%m%d-%H%M%S') + '.json'))
        except OSError:
            pass
        log('ek_fikir: bozuk veri dosyası kenara alındı', type(exc).__name__)
        return {'v': 1, 'savedAt': 0, 'items': {}}


def _yedekle() -> None:
    p = veri_yolu()
    try:
        if not p.exists():
            return
        gun = time.strftime('%Y-%m-%d')
        hedef = _yedek_dizini() / f'fikir-veri-{gun}.json'
        if not hedef.exists():
            shutil.copyfile(p, hedef)
            eski = sorted(_yedek_dizini().glob('fikir-veri-*.json'))
            for f in eski[:-7]:
                try:
                    f.unlink()
                except OSError:
                    pass
    except Exception as exc:
        log('ek_fikir: yedek alınamadı', type(exc).__name__, exc)


def snapshot_yaz(snap: dict) -> None:
    try:
        from . import ek_yayin as _Y          # yayın modu: DEMO veri yalnızca bellekte tutulur, diske yazılmaz
        if _Y.kat('fikir'):
            _Y.fikir_yaz(snap)
            return
    except Exception:
        pass
    p = veri_yolu()
    _yedekle()
    snap = {'v': 1, 'savedAt': int(time.time() * 1000), 'items': snap.get('items', {})}
    tmp = p.with_name(p.name + '.tmp')
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(snap, ensure_ascii=False), 'utf-8')
        for i in range(10):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == 9:
                    p.write_text(tmp.read_text('utf-8'), 'utf-8')     # son çare: doğrudan yaz
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                else:
                    time.sleep(0.1)
    except OSError as exc:
        log('ek_fikir: veri yazılamadı', exc)
        raise


def _json_oku(items: dict, key: str, varsayilan):
    try:
        raw = items.get(key)
        return json.loads(raw) if raw else varsayilan
    except Exception:
        return varsayilan


_YOK = object()


def _kimlikli(x) -> bool:
    return isinstance(x, list) and all(isinstance(e, dict) and 'id' in e for e in x)


def _bir(b, c, s):
    """Üçlü birleştirme: b=taban (sayfanın bildiği), c=sayfanın şimdiki, s=sunucudaki (yapay zekâ değiştirmiş olabilir).
    Kimlikli listeler (görevler, notlar…) kimliğe göre birleşir; sayfanın silmesi/eklemesi ile yapay zekânın eklemesi/değişikliği birbirini ezmez."""
    if c == b:
        return s
    if s == b or c == s:
        return c
    if c is _YOK:
        return s
    if s is _YOK:
        return c
    if isinstance(c, dict) and isinstance(s, dict):
        bd = b if isinstance(b, dict) else {}
        out = {}
        for k in list(s) + [k for k in c if k not in s]:
            r = _bir(bd.get(k, _YOK), c.get(k, _YOK), s.get(k, _YOK))
            if r is not _YOK:
                out[k] = r
        return out
    if _kimlikli(c) and _kimlikli(s):
        bl = {str(e['id']): e for e in b} if _kimlikli(b) else {}
        cl = {str(e['id']): e for e in c}
        sl = {str(e['id']): e for e in s}
        out = []
        for k in list(sl) + [k for k in cl if k not in sl]:
            r = _bir(bl.get(k, _YOK), cl.get(k, _YOK), sl.get(k, _YOK))
            if r is not _YOK:
                out.append(r)
        return out
    return c        # birleştirilemeyen çakışma: kullanıcının kendi elle yaptığı değişiklik kazanır


def birlestir(taban: dict, istemci: dict, sunucu: dict) -> dict:
    out = {}
    for k in list(sunucu) + [k for k in istemci if k not in sunucu]:
        b, c, sv = taban.get(k, _YOK), istemci.get(k, _YOK), sunucu.get(k, _YOK)
        if c == b:
            r = sv
        elif sv == b or c == sv:
            r = c
        elif c is _YOK:
            r = sv
        elif sv is _YOK:
            r = c
        else:
            try:
                pb = json.loads(b) if b is not _YOK else _YOK
                pc, ps = json.loads(c), json.loads(sv)
                if pc == pb:
                    r = sv
                elif ps == pb or pc == ps:
                    r = c
                else:
                    r = json.dumps(_bir(pb, pc, ps), ensure_ascii=False)
            except Exception:
                r = c
        if r is not _YOK:
            out[k] = r
    return out


def duzenle(fn):
    """Kilit altında oku → fn(items) → yaz → sürümü artır → sayfayı tazele. fn'nin dönüşünü verir."""
    with _L:
        snap = snapshot_oku()
        _F['onceki'].setdefault(_F['epoch'], dict(snap['items']))     # sayfanın son bildiği hal: PUT çakışmasında 3'lü birleştirme tabanı
        while len(_F['onceki']) > 8:
            _F['onceki'].pop(next(iter(_F['onceki'])))
        sonuc = fn(snap['items'])
        snapshot_yaz(snap)
        _F['epoch'] += 1
    try:
        _ek()._hud('ekFikirYenile')
    except Exception:
        pass
    _uyandir_izleyici()
    return sonuc


# --------------------------------------------------------------------------- tarih/saat yardımcıları
def _fold(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(text or '').replace('İ', 'i').replace('I', 'ı').lower())
    t = ''.join(c for c in t if not unicodedata.combining(c)).replace('ı', 'i')
    return re.sub(r'\s+', ' ', t).strip()


def bugun() -> dt.date:
    return dt.date.today()


def gun_coz(metin: str | None, varsayilan: dt.date | None = None) -> dt.date | None:
    """'bugün', 'yarın', 'cuma', '2026-11-03', '3.11' → tarih. Çözülemezse varsayılan."""
    if metin is None or not str(metin).strip():
        return varsayilan
    t = _fold(metin)
    bu = bugun()
    if t in ('bugun', 'today', 'simdi', 'bu gun'):
        return bu
    if t in ('yarin', 'tomorrow'):
        return bu + dt.timedelta(days=1)
    if t in ('obur gun', 'ertesi gun', 'yarindan sonra'):
        return bu + dt.timedelta(days=2)
    if t == 'dun':
        return bu - dt.timedelta(days=1)
    if t in ('haftaya', 'gelecek hafta', 'seneye'):
        return bu + dt.timedelta(days=7)
    for i, ad in enumerate(TR_GUN_ASCII):
        if t == ad or t == 'bu ' + ad or t == 'gelecek ' + ad or t == 'haftaya ' + ad:
            fark = (i - bu.weekday()) % 7
            if fark == 0 and t != 'bu ' + ad and t != ad:
                fark = 7
            if t.startswith('gelecek ') or t.startswith('haftaya '):
                fark = fark if fark else 7
            return bu + dt.timedelta(days=fark)
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', t)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return varsayilan
    m = re.match(r'^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$', t)
    if m:
        try:
            y = int(m[3]) if m[3] else bu.year
            y += 2000 if y < 100 else 0
            d = dt.date(y, int(m[2]), int(m[1]))
            if not m[3] and d < bu - dt.timedelta(days=30):
                d = d.replace(year=y + 1)
            return d
        except ValueError:
            return varsayilan
    return varsayilan


def saat_coz(metin: str | None) -> str | None:
    if not metin:
        return None
    m = re.search(r'(\d{1,2})\s*[:.]\s*(\d{2})', str(metin))
    if m and 0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59:
        return f'{int(m[1]):02d}:{m[2]}'
    m = re.fullmatch(r'\s*(\d{1,2})\s*', str(metin))
    if m and 0 <= int(m[1]) <= 23:
        return f'{int(m[1]):02d}:00'
    return None


def metinden_saat(text: str) -> tuple[str | None, str]:
    """'14:30 Doktora git' → ('14:30', 'Doktora git')."""
    m = SAAT_RE.search(text or '')
    if not m:
        return None, (text or '').strip()
    temiz = (text[:m.start()] + ' ' + text[m.end():]).strip(' -–—·,')
    temiz = re.sub(r'\s{2,}', ' ', temiz).strip()
    return f'{int(m[1]):02d}:{m[2]}', temiz or (text or '').strip()


def saatli_metin(saat: str | None, metin: str) -> str:
    metin = (metin or '').strip()
    return f'{saat} {metin}'.strip() if saat else metin


# --------------------------------------------------------------------------- veri erişimi
def _gizli_idler(items: dict) -> set:
    cats = _json_oku(items, KEY_CATS, [])
    out = set()
    if isinstance(cats, list):
        for c in cats:
            if isinstance(c, dict) and (c.get('aiHidden') or _fold(c.get('name', '')) == 'gizli'):
                out.add(c.get('id'))
    return out


def _kategori_adi(items: dict, cid) -> str:
    for c in _json_oku(items, KEY_CATS, []) or []:
        if isinstance(c, dict) and c.get('id') == cid:
            return str(c.get('name', ''))
    return ''


def gorevler(items: dict | None = None, gizli_dahil: bool = False) -> list[dict]:
    """Görünüm listesi: {id, metin, saat, gun, bitti, oncelik, kat, ham}. Gizli kategoriler hariç (yapay zekâ için)."""
    if items is None:
        items = snapshot_oku()['items']
    raw = _json_oku(items, KEY_TASKS, [])
    gizli = set() if gizli_dahil else _gizli_idler(items)
    out = []
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict) or not str(t.get('text', '')).strip():
            continue
        if t.get('cat') in gizli and t.get('cat') is not None:
            continue
        saat, temiz = metinden_saat(str(t.get('text', '')))
        out.append({'id': str(t.get('id', '')), 'metin': temiz, 'saat': saat, 'gun': str(t.get('day') or ''),
                    'bitti': bool(t.get('done')), 'oncelik': t.get('priority') or 'normal',
                    'kat': _kategori_adi(items, t.get('cat')), 'ham': t})
    return out


def gorev_ts(g: dict) -> tuple[int, bool]:
    gun = gun_coz(g.get('gun'), bugun())
    if g.get('saat'):
        h, m = g['saat'].split(':')
        return int(dt.datetime.combine(gun, dt.time(int(h), int(m))).timestamp()), False
    return int(dt.datetime.combine(gun, dt.time(0, 0)).timestamp()), True


def _yeni_id() -> str:
    return str(uuid.uuid4())


def _kategori_bul(items: dict, ad: str | None):
    if not ad:
        return None
    cats = _json_oku(items, KEY_CATS, [])
    f = _fold(ad)
    gizli = _gizli_idler(items)
    for c in cats if isinstance(cats, list) else []:
        if isinstance(c, dict) and c.get('id') not in gizli and _fold(c.get('name', '')) == f:
            return c.get('id')
    return None


def gorev_ekle(metin: str, gun=None, saat: str | None = None, oncelik: str = 'normal', kategori: str | None = None) -> dict:
    metin = ' '.join(str(metin or '').split())[:200]
    if not metin:
        raise ValueError('Görev metni boş.')
    s2, temiz = metinden_saat(metin)
    saat = saat_coz(saat) or s2
    metin = temiz if s2 else metin
    d = gun_coz(gun, bugun()) if not isinstance(gun, dt.date) else gun
    onc = oncelik if oncelik in ONCELIK else 'normal'
    kayit = {}

    def fn(items):
        raw = _json_oku(items, KEY_TASKS, [])
        if not isinstance(raw, list):
            raw = []
        # aynı gün aynı metin zaten açık mı?
        for t in raw:
            if isinstance(t, dict) and not t.get('done') and t.get('day') == d.isoformat():
                s_, c_ = metinden_saat(str(t.get('text', '')))
                if _fold(c_) == _fold(metin) and s_ == saat:
                    kayit.update(t)
                    kayit['_var'] = True
                    return
        t = {'id': _yeni_id(), 'text': saatli_metin(saat, metin), 'done': False, 'cat': _kategori_bul(items, kategori),
             'day': d.isoformat(), 'doneDay': None, 'carried': False, 'priority': onc}
        raw.insert(0, t)
        items[KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
        kayit.update(t)
    duzenle(fn)
    return {'id': kayit.get('id'), 'metin': metin, 'saat': saat, 'gun': d.isoformat(), 'var': bool(kayit.get('_var'))}


def _eslestir(items: dict, anahtar: str, bitmemis: bool = True):
    """Görevi kimliğiyle ya da metin parçasıyla bul. (liste, [indeksler]) döner."""
    raw = _json_oku(items, KEY_TASKS, [])
    raw = raw if isinstance(raw, list) else []
    gizli = _gizli_idler(items)
    a = _fold(anahtar)
    ids = [i for i, t in enumerate(raw) if isinstance(t, dict) and str(t.get('id')) == str(anahtar)]
    if ids:
        return raw, ids
    hit = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict) or (bitmemis and t.get('done')) or (t.get('cat') in gizli and t.get('cat') is not None):
            continue
        _, temiz = metinden_saat(str(t.get('text', '')))
        f = _fold(temiz)
        if a and (a == f or a in f or f in a and len(f) >= 4):
            hit.append(i)
    exact = [i for i in hit if _fold(metinden_saat(str(raw[i].get('text', '')))[1]) == a]
    return raw, exact or hit


def gorev_bitir(anahtar: str, yapildi: bool = True) -> list[str]:
    adlar = []

    def fn(items):
        raw, idx = _eslestir(items, anahtar, bitmemis=yapildi)
        if len(idx) != 1:
            adlar.extend(['?'] * len(idx))
            return
        t = raw[idx[0]]
        t['done'] = bool(yapildi)
        t['doneDay'] = bugun().isoformat() if yapildi else None
        adlar.append(metinden_saat(str(t.get('text', '')))[1])
        items[KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
    duzenle(fn)
    return adlar


def gorev_sil(anahtar: str) -> list[str]:
    adlar = []

    def fn(items):
        raw, idx = _eslestir(items, anahtar, bitmemis=False)
        if len(idx) != 1:
            adlar.extend(['?'] * len(idx))
            return
        t = raw.pop(idx[0])
        adlar.append(metinden_saat(str(t.get('text', '')))[1])
        trash = _json_oku(items, KEY_TRASH, [])
        trash = trash if isinstance(trash, list) else []
        trash.append({'id': _yeni_id(), 'kind': 'task', 'title': adlar[0][:140], 'deletedAt': dt.datetime.utcnow().isoformat() + 'Z', 'data': t})
        items[KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
        items[KEY_TRASH] = json.dumps(trash, ensure_ascii=False)
    duzenle(fn)
    return adlar


def gorev_duzenle(anahtar: str, yeni_metin: str | None = None, gun=None, saat: str | None = None, oncelik: str | None = None) -> str:
    sonuc = []

    def fn(items):
        raw, idx = _eslestir(items, anahtar)
        if len(idx) != 1:
            sonuc.append(('coklu' if idx else 'yok', len(idx)))
            return
        t = raw[idx[0]]
        s0, m0 = metinden_saat(str(t.get('text', '')))
        m1 = ' '.join(str(yeni_metin).split())[:200] if yeni_metin else m0
        s1 = saat_coz(saat) if saat is not None and saat != '' else s0
        if saat == '-':
            s1 = None
        s_in, temiz = metinden_saat(m1)
        if s_in and yeni_metin:
            s1, m1 = s_in, temiz
        t['text'] = saatli_metin(s1, m1)
        if gun:
            d = gun_coz(gun, None)
            if d:
                t['day'] = d.isoformat()
        if oncelik in ONCELIK:
            t['priority'] = oncelik
        items[KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
        sonuc.append(('ok', t['text']))
    duzenle(fn)
    d, v = sonuc[0] if sonuc else ('yok', 0)
    if d == 'ok':
        return f'Güncellendi: {v}'
    if d == 'coklu':
        return f'“{anahtar}” {v} göreve uyuyor; hangisi? (daha açık yaz)'
    return f'“{anahtar}” adlı açık görev bulunamadı.'


NOT_MAX = 19500        # Fikir'deki not düzenleyicisi 20.000 karakterde keser; taşan kısım "(devam N)" notuna gider
_RENKLER = ['#ffffff', '#f3f8fb', '#f8f6ed', '#edf5f7', '#f4f1fa', '#f4f7f3']


def _board(items: dict) -> dict:
    board = _json_oku(items, KEY_BOARD, None)
    if not isinstance(board, dict):
        board = {'version': 6, 'notes': [], 'strokes': [], 'links': [], 'camera': {'x': 0, 'y': 0}}
    if not isinstance(board.get('notes'), list):
        board['notes'] = []
    return board


def _yeni_not(board: dict, baslik: str, metin: str, etiketler: list | None = None) -> dict:
    """Kamera çevresinde dolu olmayan ilk yuvaya yeni not ekler."""
    notes = board['notes']
    cam = board.get('camera') if isinstance(board.get('camera'), dict) else {}
    n = len(notes)
    cx, cy = float(cam.get('x', 0) or 0), float(cam.get('y', 0) or 0)
    offs = [(0, 0), (300, 0), (-300, 0), (0, 255), (0, -255), (300, 255), (-300, 255), (300, -255), (-300, -255), (600, 0), (-600, 0),
            (600, 255), (-600, 255), (900, 0), (-900, 0), (0, 510), (300, 510), (-300, 510)]
    x, y = cx + n * 280, cy
    for dx, dy in offs:
        if not any(abs(float(q.get('x', 0)) - (cx + dx)) < 250 and abs(float(q.get('y', 0)) - (cy + dy)) < 205 for q in notes if isinstance(q, dict)):
            x, y = cx + dx, cy + dy
            break
    note = {'id': _yeni_id(), 'text': metin, 'title': str(baslik or '')[:80], 'x': x, 'y': y,
            'color': _RENKLER[n % 6], 'textColor': '#2d4150', 'opacity': 100,
            'categoryId': None, 'priority': 'normal', 'size': 'large' if len(metin) > 600 else 'medium', 'shape': 'rounded',
            'fontSize': 13, 'depth': 0, 'pinned': False, 'tags': list(etiketler or [])[:12]}
    notes.append(note)
    return note


def parcala(metin: str, sinir: int = NOT_MAX) -> list[str]:
    """Metni paragraf/satır/cümle sınırlarında ≤ sinir karakterlik parçalara böler (hiçbir şey atılmaz)."""
    metin = str(metin or '').strip()
    out = []
    while len(metin) > sinir:
        kes = -1
        for ayrac in ('\n\n', '\n', '. ', ' '):
            kes = metin.rfind(ayrac, int(sinir * 0.5), sinir)
            if kes > 0:
                kes += len(ayrac)
                break
        if kes <= 0:
            kes = sinir
        out.append(metin[:kes].rstrip())
        metin = metin[kes:].lstrip()
    if metin:
        out.append(metin)
    return out


def _kelimeler(t: str) -> set:
    return {w for w in re.sub(r'[^a-z0-9]+', ' ', _fold(t)).split() if len(w) >= 3}


def _not_eslestir(notes: list, gizli: set, baslik: str):
    """Başlığa güçlü biçimde uyan notu (yoksa None) bulur: eşit/içerme ya da kelime örtüşmesi >= %60. (devam N) notlarını atlar."""
    f = _fold(baslik).strip()
    if not f:
        return None
    kw = _kelimeler(baslik)
    en, skor_en = None, 0.0
    for q in notes:
        if not isinstance(q, dict) or (q.get('categoryId') in gizli and q.get('categoryId') is not None):
            continue
        t = str(q.get('title') or '')
        if re.search(r'\(devam \d+\)\s*$', t):
            continue
        ft = _fold(t).strip()
        if not ft:
            continue
        if ft == f:
            skor = 2.0
        elif len(ft) >= 4 and len(f) >= 4 and (ft in f or f in ft):
            skor = 1.5
        else:
            kt = _kelimeler(t)
            skor = len(kw & kt) / max(1, min(len(kw), len(kt))) if kw and kt else 0.0
            if skor < 0.6 or len(kw & kt) < 2:
                skor = 0.0
        if skor > skor_en:
            en, skor_en = q, skor
    return en


def not_yaz(baslik: str, metin: str, ekle: bool = True, etiketler: list | None = None) -> dict:
    """Fikir panosuna not yazar. ekle=True ve başlığa güçlü uyan bir not varsa ONUN SONUNA ekler (üstüne yazmaz);
    yoksa yeni not açar. 20.000 karakteri aşan metin kısaltılmaz: '(devam 2)', '(devam 3)' notlarına bölünür.
    Döner: {'baslik','yeni','notlar':[kimlikler],'uzunluk','eklenen':ilk notun başlığı}"""
    metin = str(metin or '').strip()
    baslik = ' '.join(str(baslik or '').split())[:80]
    if not metin:
        raise ValueError('Not metni boş.')
    if not baslik:
        baslik = ' '.join(metin.split()[:6])[:80]
    sonuc = {}

    def fn(items):
        board = _board(items)
        notes = board['notes']
        hedef = _not_eslestir(notes, _gizli_idler(items), baslik) if ekle else None
        kalan = metin
        kimlikler = []
        if hedef is not None:
            ad = str(hedef.get('title') or baslik)
            mevcut = str(hedef.get('text') or '')
            ayrac = f'\n\n— {time.strftime("%d.%m.%Y %H:%M")} —\n'
            bos = NOT_MAX - len(mevcut) - len(ayrac)
            if bos >= 800:
                ilk = parcala(kalan, bos)[0]
                hedef['text'] = mevcut + ayrac + ilk
                if len(hedef['text']) > 600:
                    hedef['size'] = 'large'
                kalan = kalan[len(ilk):].lstrip()
                kimlikler.append(str(hedef.get('id')))
            sonuc['yeni'] = False
            sonuc['eklenen'] = ad
            ilk_baslikli = False
        else:
            ad = baslik
            sonuc['yeni'] = True
            ilk_baslikli = True
        devam = 2 + sum(1 for q in notes if isinstance(q, dict) and str(q.get('title') or '').startswith(f'{ad} (devam'))
        for parca in parcala(kalan) if kalan else []:
            if ilk_baslikli:
                t, ilk_baslikli = ad, False
            else:
                t, devam = f'{ad} (devam {devam})', devam + 1
            kimlikler.append(_yeni_not(board, t, parca, etiketler)['id'])
        items[KEY_BOARD] = json.dumps(board, ensure_ascii=False)
        sonuc['notlar'] = kimlikler
        sonuc['baslik'] = ad
        sonuc['uzunluk'] = len(metin)
    duzenle(fn)
    return sonuc


def fikir_ekle(metin: str, baslik: str = '') -> str:
    metin = str(metin or '').strip()
    if not metin and not baslik:
        raise ValueError('Fikir boş.')
    r = not_yaz(baslik, metin or baslik, ekle=False)
    return (r.get('notlar') or [''])[0]


def fikirler(items: dict | None = None) -> list[dict]:
    if items is None:
        items = snapshot_oku()['items']
    board = _json_oku(items, KEY_BOARD, {})
    gizli = _gizli_idler(items)
    out = []
    for n in (board.get('notes') if isinstance(board, dict) else None) or []:
        if not isinstance(n, dict) or (n.get('categoryId') in gizli and n.get('categoryId') is not None):
            continue
        out.append({'id': str(n.get('id', '')), 'baslik': str(n.get('title', '')), 'metin': str(n.get('text', '')),
                    'kat': _kategori_adi(items, n.get('categoryId'))})
    return out


# --------------------------------------------------------------------------- haftalık program
def hafta_bloklari(items: dict | None = None) -> list[dict]:
    if items is None:
        items = snapshot_oku()['items']
    w = _json_oku(items, KEY_WEEK, {})
    return [b for b in (w.get('blocks') if isinstance(w, dict) else None) or [] if isinstance(b, dict)]


def _pazartesi(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def hafta_ekle(baslik: str, gun, baslangic: str, sure_dk: int = 60, tekrar: bool = False, renk: str = 'focus', not_: str = '') -> dict:
    d = gun_coz(gun, None) if not isinstance(gun, dt.date) else gun
    if d is None:
        raise ValueError('Gün anlaşılamadı.')
    saat = saat_coz(baslangic)
    if not saat:
        raise ValueError('Başlangıç saati anlaşılamadı (ör. 14:30).')
    h, m = saat.split(':')
    bas = int(h) * 60 + int(m)
    bas = round(bas / 15) * 15
    sure = max(15, min(720, round(int(sure_dk or 60) / 15) * 15))
    blok = {'id': 'wb-' + uuid.uuid4().hex[:10], 'day': d.weekday(), 'start': min(bas, 1439), 'dur': sure,
            'title': ' '.join(str(baslik).split())[:80], 'color': renk if renk in RENKLER else 'focus', 'note': str(not_ or '')[:240],
            'once': not tekrar, 'week': _pazartesi(d).isoformat() if not tekrar else None}
    if not blok['title']:
        raise ValueError('Blok başlığı boş.')

    def fn(items):
        w = _json_oku(items, KEY_WEEK, None)
        if not isinstance(w, dict) or not isinstance(w.get('blocks'), list):
            w = {'version': 1, 'blocks': [], 'done': w.get('done', {}) if isinstance(w, dict) else {}}
        for b in w['blocks']:
            if isinstance(b, dict) and b.get('day') == blok['day'] and b.get('start') == blok['start'] and _fold(b.get('title', '')) == _fold(blok['title']) \
                    and (b.get('once') == blok['once']) and (b.get('week') == blok['week']):
                return
        w['blocks'].append(blok)
        items[KEY_WEEK] = json.dumps(w, ensure_ascii=False)
    duzenle(fn)
    return blok


def hafta_etkinlikleri(baslangic: dt.datetime, bitis: dt.datetime) -> list[dict]:
    """[baslangic, bitis) ile kesişen Fikir haftalık blokları, win_agenda'nın etkinlik biçiminde."""
    out = []
    try:
        bloklar = hafta_bloklari()
    except Exception:
        return out
    if not bloklar:
        return out
    gun = baslangic.date() - dt.timedelta(days=1)
    son = bitis.date()
    lo, hi = baslangic.timestamp(), bitis.timestamp()
    while gun <= son:
        pzt = _pazartesi(gun).isoformat()
        for b in bloklar:
            try:
                if int(b.get('day', -1)) != gun.weekday():
                    continue
                if b.get('once') and b.get('week') != pzt:
                    continue
                t0 = dt.datetime.combine(gun, dt.time(0, 0)) + dt.timedelta(minutes=int(b.get('start', 0)))
                t1 = t0 + dt.timedelta(minutes=int(b.get('dur', 60)))
                if t1.timestamp() > lo and t0.timestamp() < hi:
                    out.append({'start_ts': int(t0.timestamp()), 'end_ts': int(t1.timestamp()), 'calendar': 'Fikir Haftası',
                                'title': str(b.get('title', '')) or 'Blok', 'location': '', 'all_day': False})
            except Exception:
                continue
        gun += dt.timedelta(days=1)
    return out


# --------------------------------------------------------------------------- özet (yapay zekâ için)
def ozet(kapsam: str = 'bugun', limit: int = 40) -> str:
    items = snapshot_oku()['items']
    bu = bugun()
    gs = gorevler(items)
    acik = [g for g in gs if not g['bitti']]
    satir = []
    k = _fold(kapsam)

    def g_satir(g):
        gun = gun_coz(g['gun'], bu)
        etiket = 'bugün' if gun == bu else ('yarın' if gun == bu + dt.timedelta(days=1) else f'{gun.day}.{gun.month:02d}')
        onc = {'high': ' ❗', 'important': ' ⭑'}.get(g['oncelik'], '')
        return f'- {(g["saat"] + " ") if g["saat"] else ""}{g["metin"]} [{etiket}{", " + g["kat"] if g["kat"] else ""}]{onc}'

    if k in ('bugun', 'today', ''):
        bg = [g for g in acik if gun_coz(g['gun'], bu) <= bu]
        bg.sort(key=lambda g: (g['saat'] or '99:99'))
        yap = [g for g in gs if g['bitti'] and g['gun'] == bu.isoformat()]
        satir.append(f'BUGÜN ({TR_GUN[bu.weekday()]}, {bu.day}.{bu.month:02d}): {len(bg)} açık görev, {len(yap)} bitti.')
        satir += [g_satir(g) for g in bg[:limit]]
        bl = [e for e in hafta_etkinlikleri(dt.datetime.combine(bu, dt.time(0, 0)), dt.datetime.combine(bu + dt.timedelta(days=1), dt.time(0, 0)))]
        for e in sorted(bl, key=lambda e: e['start_ts']):
            satir.append(f'- {dt.datetime.fromtimestamp(e["start_ts"]):%H:%M}–{dt.datetime.fromtimestamp(e["end_ts"]):%H:%M} {e["title"]} [haftalık program]')
    elif k in ('hafta', 'week'):
        for i in range(7):
            d = bu + dt.timedelta(days=i)
            satir.append(f'{TR_GUN[d.weekday()]} {d.day}.{d.month:02d}' + (' (bugün)' if i == 0 else ''))
            evs = hafta_etkinlikleri(dt.datetime.combine(d, dt.time(0, 0)), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0, 0)))
            for e in sorted(evs, key=lambda e: e['start_ts']):
                satir.append(f'  {dt.datetime.fromtimestamp(e["start_ts"]):%H:%M}–{dt.datetime.fromtimestamp(e["end_ts"]):%H:%M} {e["title"]}')
            for g in acik:
                if gun_coz(g['gun'], bu) == d:
                    satir.append('  ' + g_satir(g)[2:])
    elif k in ('fikir', 'fikirler', 'ideas', 'notlar'):
        fl = fikirler(items)
        satir.append(f'{len(fl)} fikir:')
        for f in fl[-limit:]:
            satir.append(f'- {(f["baslik"] + ": ") if f["baslik"] else ""}{" ".join(f["metin"].split())[:160]}')
    else:
        satir.append(f'AÇIK GÖREVLER ({len(acik)}):')
        satir += [g_satir(g) for g in sorted(acik, key=lambda g: (g['gun'], g['saat'] or '99:99'))[:limit]]
    return '\n'.join(satir) if satir else 'Fikir Alanım boş.'


def ara(sorgu: str, limit: int = 15) -> str:
    items = snapshot_oku()['items']
    toks = [t for t in _fold(sorgu).split() if len(t) >= 2]
    if not toks:
        return 'Aranacak bir söz ver.'
    sat = []
    for g in gorevler(items):
        f = _fold(g['metin'] + ' ' + g['kat'])
        if all(t in f for t in toks):
            sat.append(f'görev{" (bitti)" if g["bitti"] else ""}: {g["saat"] + " " if g["saat"] else ""}{g["metin"]} [{g["gun"]}]')
    for n in fikirler(items):
        f = _fold(n['baslik'] + ' ' + n['metin'])
        if all(t in f for t in toks):
            sat.append(f'fikir: {(n["baslik"] + ": ") if n["baslik"] else ""}{" ".join(n["metin"].split())[:140]}')
    for b in hafta_bloklari(items):
        if all(t in _fold(b.get('title', '')) for t in toks):
            sat.append(f'program: {TR_GUN[int(b.get("day", 0)) % 7]} {int(b.get("start", 0)) // 60:02d}:{int(b.get("start", 0)) % 60:02d} {b.get("title", "")}')
    return '\n'.join(sat[:limit]) if sat else 'Fikir Alanım\'da bulamadım.'


def sayilar() -> dict:
    try:
        items = snapshot_oku()['items']
        gs = gorevler(items, gizli_dahil=True)
        return {'acik': sum(1 for g in gs if not g['bitti']), 'fikir': len(fikirler(items)), 'blok': len(hafta_bloklari(items)),
                'var': bool(items)}
    except Exception:
        return {'acik': 0, 'fikir': 0, 'blok': 0, 'var': False}


# --------------------------------------------------------------------------- anımsatıcı ↔ görev (win_agenda köprüsü)
def hatirlatici_satirlari() -> list[dict]:
    """Açık Fikir görevleri, win_agenda.reminder_rows biçiminde (id 'fk:<görev>')."""
    out = []
    bu = bugun()
    for g in gorevler():
        if g['bitti']:
            continue
        gun = gun_coz(g['gun'], bu)
        if gun < bu - dt.timedelta(days=14):
            continue
        ts, tum = gorev_ts(g)
        out.append({'id': 'fk:' + g['id'], 'title': g['metin'], 'list_name': 'Fikir', 'notes': '', 'completed': False,
                    'priority': ONCELIK.get(g['oncelik'], 0), 'due_ts': ts, 'all_day': tum})
    return out


def _mod_suz(rows: list[dict], mode: str) -> list[dict]:
    now = time.time()
    today = dt.datetime.combine(bugun(), dt.time(0, 0)).timestamp()
    if mode == 'today':
        return [r for r in rows if r['due_ts'] and today <= r['due_ts'] < today + 86400]
    if mode == 'overdue':
        return [r for r in rows if r['due_ts'] and r['due_ts'] + (86400 if r['all_day'] else 0) < now]
    if mode in ('next', 'upcoming'):
        span = 30 if mode == 'next' else 7
        return [r for r in rows if r['due_ts'] and now <= r['due_ts'] + (86400 if r['all_day'] else 0) and r['due_ts'] <= now + span * 86400]
    return rows


_wa = {'sarili': False}


def agenda_sar() -> bool:
    """win_agenda'yı çalışma anında Fikir'e bağlar: anımsatıcılar Fikir görevleridir, takvim haftalık programı da gösterir."""
    try:
        from . import win_agenda as wa
    except Exception as exc:
        log('ek_fikir: win_agenda yok', exc)
        return False
    with _L:
        if _wa['sarili']:
            return True
        o_rows, o_ev = wa.reminder_rows, wa.events_between
        o_add, o_del, o_done = wa.add_reminder, wa.delete_reminder, wa.complete_reminder

        def reminder_rows(mode='all', limit=20, list_name=''):
            try:
                eski = list(o_rows(mode, 20, list_name))
            except Exception:
                eski = []
            try:
                yeni = _mod_suz(hatirlatici_satirlari(), mode) if not list_name or _fold(list_name) in ('fikir', '') else []
            except Exception as exc:
                log('ek_fikir: görevler okunamadı', type(exc).__name__)
                yeni = []
            rows = eski + yeni
            rows.sort(key=lambda r: (r['due_ts'] <= 0, r['due_ts'] or 0, r['title'].lower()))
            return rows[:1 if mode == 'next' else max(1, min(20, int(limit or 20)))]

        def events_between(start, end):
            ev = list(o_ev(start, end))
            try:
                ev += hafta_etkinlikleri(start, end)
            except Exception:
                pass
            return sorted(ev, key=lambda e: (e['start_ts'], e['title'].lower()))

        def add_reminder(title, due_iso='', notes='', list_name='', priority='', all_day=False):
            from .actions import reminders as rem
            if not title or not str(title).strip():
                return 'Animsatici basligi bos olamaz.'
            gun, saat = bugun(), None
            if due_iso and str(due_iso).strip():
                try:
                    norm, inferred = rem._normalize_due_iso(due_iso)
                except ValueError as exc:
                    return str(exc)
                m = re.match(r'^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?', norm)
                if not m:
                    return "Animsatici tarihi gecersiz. due_iso icin 'YYYY-MM-DD' veya 'YYYY-MM-DDTHH:MM' kullan."
                gun = dt.date(int(m[1]), int(m[2]), int(m[3]))
                if m[4] is not None and not (all_day or inferred):
                    saat = f'{int(m[4]):02d}:{m[5]}'
            onc = {'high': 'high', 'yuksek': 'high', 'orta': 'important', 'medium': 'important', 'important': 'important'}.get(str(priority or '').lower(), 'normal')
            r = gorev_ekle(str(title), gun, saat, onc)
            ne = f'{"bugün" if gun == bugun() else f"{gun.day}.{gun.month:02d}"}{" " + saat if saat else ""}'
            if r.get('var'):
                return f'Anımsatıcı zaten var: {ne} - {r["metin"]}'
            ek = ''
            if saat and gun == bugun():
                h, m_ = saat.split(':')
                if dt.datetime.combine(gun, dt.time(int(h), int(m_))) < dt.datetime.now() - dt.timedelta(minutes=2):
                    ek = ' (Dikkat: bu saat geçti. Saat yanlışsa kullanıcıya sor, gerekirse sil.)'
            return f'Animsatici eklendi (Fikir Alanım görevi): {ne} - {r["metin"]}{ek}'

        def _degistir(action, title, due_iso, list_name, every, reminder_id):
            from .actions import reminders as rem
            rows = reminder_rows('all', 20, '') if not list_name else reminder_rows('all', 20, list_name)
            if not reminder_id and not list_name:
                pass
            targets, answer = rem.pick_targets(action, rows, title, due_iso, (reminder_id or '').strip(), every)
            if answer:
                return answer
            for t in targets:
                tid = str(t.get('id', ''))
                if tid.startswith('fk:'):
                    if action == 'delete':
                        gorev_sil(tid[3:])
                    else:
                        gorev_bitir(tid[3:])
                else:
                    (o_del if action == 'delete' else o_done)(reminder_id=tid)
            return rem.changed_text(action, targets)

        def delete_reminder(title='', due_iso='', list_name='', delete_all_matches=False, reminder_id=''):
            return _degistir('delete', title, due_iso, list_name, delete_all_matches, reminder_id)

        def complete_reminder(title='', due_iso='', list_name='', reminder_id=''):
            return _degistir('complete', title, due_iso, list_name, False, reminder_id)

        wa.reminder_rows, wa.events_between = reminder_rows, events_between
        wa.add_reminder, wa.delete_reminder, wa.complete_reminder = add_reminder, delete_reminder, complete_reminder
        _wa['sarili'] = True
    log('ek_fikir: anımsatıcılar ve takvim Fikir Alanım\'a bağlandı')
    return True


# --------------------------------------------------------------------------- saati gelen görevleri duyur
_uyan = threading.Event()


def _uyandir_izleyici() -> None:
    _uyan.set()


def duyurulacaklar(now: dt.datetime | None = None, onceki: set | None = None) -> list[tuple[str, dict]]:
    """Saati gelmiş (ve geçmeyeli ≤ 90 dk), bugünkü, bitmemiş saatli görevler: [(anahtar, görev)]."""
    now = now or dt.datetime.now()
    out = []
    for g in gorevler():
        if g['bitti'] or not g['saat']:
            continue
        gun = gun_coz(g['gun'], None)
        if gun != now.date():
            continue
        h, m = g['saat'].split(':')
        vakit = dt.datetime.combine(gun, dt.time(int(h), int(m)))
        if vakit > now:
            continue
        anahtar = f'{g["id"]}|{g["gun"]}|{g["saat"]}'
        if onceki is not None and anahtar in onceki:
            continue
        g = dict(g)
        g['gec_dk'] = int((now - vakit).total_seconds() // 60)
        out.append((anahtar, g))
    return out


def _duyur_dongusu() -> None:
    ilk = True
    while True:
        try:
            ek = _ek()
            s = ek._state()
            gorulen = set(s.get('fikir_duyuru') or [])
            yeni = duyurulacaklar(onceki=gorulen)
            if yeni:
                for anahtar, g in yeni:
                    gorulen.add(anahtar)
                    if g['gec_dk'] > 90 and ilk:
                        continue          # BLOOM kapalıyken geçmiş: sessizce işaretle
                    if g['gec_dk'] > 90:
                        continue
                    log(f'ek_fikir: görev vakti geldi: {g["saat"]} {g["metin"]}')
                    ek._announce(f'[HATIRLATMA] Kullanıcının Fikir Alanım görevinin saati geldi: “{g["metin"]}” (saat {g["saat"]}). '
                                 'Kısaca, doğal bir cümleyle hatırlat; yapıldıysa "bitti" demesini ya da erteleme istemesini bekle.')
                    ek._hud('ekAlarm')
                ek.ayar_yaz('fikir_duyuru', sorted(gorulen)[-300:])
            ilk = False
        except Exception as exc:
            log('ek_fikir: duyuru döngüsü hatası', type(exc).__name__, exc)
        _uyan.wait(20.0)
        _uyan.clear()


# --------------------------------------------------------------------------- yerel hizmet
MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.woff2': 'font/woff2', '.png': 'image/png',
        '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json'}


def dosyalar() -> dict:
    if _F['dosyalar'] is None:
        with _L:
            if _F['dosyalar'] is None:
                d = {}
                try:
                    from . import ek_fikir_dosya
                    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(ek_fikir_dosya.ZIP_B64)))
                    for n in z.namelist():
                        if not n.endswith('/'):
                            d[n] = z.read(n)
                except Exception as exc:
                    log('ek_fikir: gömülü dosyalar okunamadı', type(exc).__name__, exc)
                _F['dosyalar'] = d
    return _F['dosyalar']


class _Handler(BaseHTTPRequestHandler):
    server_version = 'JarvisFikir'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        h = (self.headers.get('Host') or '').strip().lower()
        p = _F['port']
        return h in (f'127.0.0.1:{p}', f'localhost:{p}')

    def _cevap(self, kod: int, govde: bytes = b'', tur: str = 'text/plain; charset=utf-8', ek: dict | None = None) -> None:
        self.send_response(kod)
        self.send_header('Content-Type', tur)
        self.send_header('Content-Length', str(len(govde)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (ek or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if govde and self.command != 'HEAD':
            self.wfile.write(govde)

    def _json(self, kod: int, obj) -> None:
        self._cevap(kod, json.dumps(obj, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            if not self._host_ok():
                return self._cevap(403, b'host')
            yol = self.path.split('?', 1)[0]
            if yol == '/api/veri':
                with _L:
                    snap = snapshot_oku()
                    return self._json(200, {'v': 1, 'items': snap['items'], 'epoch': _F['epoch']})
            if yol == '/api/epoch':
                return self._json(200, {'epoch': _F['epoch']})
            if yol in ('/', ''):
                return self._cevap(302, b'', ek={'Location': '/index.html?embed=1'})
            ad = yol.lstrip('/')
            if '..' in ad or '\\' in ad:
                return self._cevap(404, b'yok')
            veri = dosyalar().get(ad)
            if veri is None:
                return self._cevap(404, b'yok')
            tur = MIME.get(os.path.splitext(ad)[1].lower(), 'application/octet-stream')
            self._cevap(200, veri, tur)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log('ek_fikir: GET hatası', type(exc).__name__, exc)
            try:
                self._cevap(500, b'hata')
            except Exception:
                pass

    def do_PUT(self):
        try:
            if not self._host_ok():
                return self._cevap(403, b'host')
            yol, _, sorgu = self.path.partition('?')
            if yol != '/api/veri':
                return self._cevap(404, b'yok')
            origin = self.headers.get('Origin')
            p = _F['port']
            if origin is not None and origin not in (f'http://127.0.0.1:{p}', f'http://localhost:{p}'):
                return self._cevap(403, b'origin')
            if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
                return self._cevap(403, b'site')
            n = int(self.headers.get('Content-Length') or 0)
            if n <= 0 or n > 40 * 1024 * 1024:
                return self._cevap(413, b'boyut')
            govde = self.rfile.read(n)
            try:
                d = json.loads(govde.decode('utf-8'))
                items = d['items']
                if not isinstance(items, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in items.items()):
                    raise ValueError
            except Exception:
                return self._cevap(400, b'bicim')
            m = re.search(r'(?:^|&)epoch=(\d+)', sorgu)
            with _L:
                if not m:
                    return self._json(409, {'epoch': _F['epoch']})
                ep = int(m[1])
                if ep == _F['epoch']:
                    snapshot_yaz({'items': items})
                    yanit = {'ok': True, 'epoch': _F['epoch']}
                else:
                    # Sayfa eski sürümle kaydediyor (bu arada yapay zekâ/anımsatıcı veriyi değiştirdi): reddetmek yerine BİRLEŞTİR;
                    # kullanıcının düzenlemesi de yapay zekânın eklediği de korunur.
                    sunucu = snapshot_oku()['items']
                    birlesik = birlestir(_F['onceki'].get(ep, {}), items, sunucu)
                    snapshot_yaz({'items': birlesik})
                    yenile = birlesik != items
                    yanit = {'ok': True, 'epoch': _F['epoch'] if not yenile else ep, 'birlesti': True, 'yenile': yenile}
            _uyandir_izleyici()
            self._json(200, yanit)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log('ek_fikir: PUT hatası', type(exc).__name__, exc)
            try:
                self._cevap(500, b'hata')
            except Exception:
                pass


def baslat() -> int:
    """Hizmeti başlatır; kullanılan portu verir (0 = başlamadı)."""
    with _L:
        if _F['srv'] is not None:
            return _F['port']
        srv = None
        for port in (PORT, 0):
            try:
                srv = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
                break
            except OSError:
                srv = None
        if srv is None:
            log('ek_fikir: yerel hizmet başlatılamadı')
            return 0
        srv.daemon_threads = True
        _F['srv'] = srv
        _F['port'] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True, name='ek-fikir-http').start()
    log(f'ek_fikir: Fikir Alanım hizmeti 127.0.0.1:{_F["port"]}')
    if not _F['izleyici']:
        _F['izleyici'] = True
        threading.Thread(target=_duyur_dongusu, daemon=True, name='ek-fikir-duyuru').start()
    return _F['port']


def adres() -> str:
    p = _F['port'] or baslat()
    return f'http://127.0.0.1:{p}/index.html?embed=1' if p else ''


# --------------------------------------------------------------------------- yapay zekâ aracı
def arac(a, _c=None) -> str:
    a = a or {}
    islem = _fold(a.get('islem', ''))
    try:
        if islem in ('oku', 'ozet', ''):
            return ozet(str(a.get('kapsam') or 'bugun'))
        if islem in ('ara',):
            return ara(str(a.get('sorgu') or a.get('metin') or ''))
        if islem == 'gorev_ekle':
            r = gorev_ekle(a.get('metin', ''), a.get('gun'), a.get('saat'), a.get('oncelik') or 'normal', a.get('kategori'))
            ne = f'{r["gun"]}{" " + r["saat"] if r["saat"] else ""}'
            return (f'Zaten vardı: {r["metin"]} ({ne}).' if r['var'] else f'Fikir Alanım\'a görev eklendi: {r["metin"]} ({ne}).') + \
                   (' Saati gelince hatırlatacağım.' if r['saat'] else '')
        if islem == 'gorev_bitir':
            adlar = gorev_bitir(str(a.get('metin') or a.get('id') or ''), True)
            if len(adlar) == 1 and adlar[0] != '?':
                return f'Tamamlandı olarak işaretlendi: {adlar[0]}'
            return 'Eşleşen tek bir açık görev bulamadım; daha açık söyler misin?' if adlar else 'Böyle açık bir görev yok.'
        if islem == 'gorev_ac':
            adlar = gorev_bitir(str(a.get('metin') or a.get('id') or ''), False)
            return f'Yeniden açıldı: {adlar[0]}' if len(adlar) == 1 and adlar[0] != '?' else 'Eşleşen bitmiş görev bulamadım.'
        from . import ek_fikir_arac as _fa
        if islem in _fa.ISLEMLER and islem != 'gorev_duzenle':
            return _fa.calistir(islem, a)
        if islem == 'gorev_duzenle':
            s = gorev_duzenle(str(a.get('metin') or a.get('id') or ''), a.get('yeni_metin'), a.get('gun'), a.get('saat'), a.get('oncelik'))
            if a.get('kategori'):
                s += ' ' + _fa.gorev_kategori({'metin': a.get('yeni_metin') or a.get('metin') or a.get('id'), 'kategori': a.get('kategori')})
            return s
        if islem == 'gorev_sil':
            adlar = gorev_sil(str(a.get('metin') or a.get('id') or ''))
            if len(adlar) == 1 and adlar[0] != '?':
                return f'Silindi (geri dönüşüm kutusunda): {adlar[0]}'
            return 'Silmek için tek bir göreve uyan açık bir ad lazım.' if adlar else 'Böyle bir görev yok.'
        if islem == 'fikir_ekle':
            r = not_yaz(a.get('baslik', ''), a.get('metin', '') or a.get('baslik', ''), ekle=False)
            return 'Fikir panoya eklendi' + (f' (uzun olduğu için {len(r["notlar"])} nota bölündü)' if len(r['notlar']) > 1 else '') + '.' if r['notlar'] else 'Eklenemedi.'
        if islem in ('nota_ekle', 'not_ekle'):
            r = not_yaz(a.get('baslik', ''), a.get('metin', ''), ekle=True)
            kisim = f' ({len(r["notlar"])} nota bölündü)' if len(r['notlar']) > 1 else ''
            return (f'“{r["baslik"]}” adlı YENİ not açıldı{kisim}.' if r['yeni'] else f'“{r["eklenen"]}” notunun sonuna eklendi{kisim}.') + f' ({r["uzunluk"]} karakter, kısaltılmadı)'
        if islem == 'not_oku':
            q = _not_eslestir(_board(snapshot_oku()['items'])['notes'], _gizli_idler(snapshot_oku()['items']), str(a.get('baslik') or a.get('metin') or ''))
            if q is None:
                return 'Bu başlığa uyan bir not bulamadım (fikirler listesi için oku/fikirler kullan).'
            t = str(q.get('text') or '')
            return f'Not “{q.get("title")}” ({len(t)} karakter):\n' + t[:6000] + ('\n… (devamı notta; sesli okuma, kısaca anlat)' if len(t) > 6000 else '')
        if islem == 'hafta_ekle':
            b = hafta_ekle(a.get('baslik', ''), a.get('gun'), str(a.get('baslangic') or a.get('saat') or ''), int(a.get('sure_dk') or 60), bool(a.get('tekrar')), a.get('renk') or 'focus')
            return f'Haftalık programa eklendi: {TR_GUN[b["day"]]} {b["start"] // 60:02d}:{b["start"] % 60:02d} ({b["dur"]} dk) {b["title"]}' + (' — her hafta.' if not b['once'] else '.')
        return 'Bilinmeyen işlem. Geçerli: oku, ara, gorev_ekle, gorev_bitir, gorev_ac, gorev_duzenle, gorev_sil, fikir_ekle, nota_ekle, hafta_ekle, ' + ', '.join(_fa.ISLEMLER) + '.'
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        log('ek_fikir: araç hatası', type(exc).__name__, exc)
        return 'Fikir Alanım işlemi şu an yapılamadı.'


def istem_blogu() -> str:
    """Her oturum başında modele: Fikir Alanım'ın bugünkü özeti + çalışma ilkeleri (kısa)."""
    try:
        s = sayilar()
        if not s['var']:
            return ''
        satirlar = ozet('bugun', 8).splitlines()
        ek_ = ''
        try:
            items = snapshot_oku()['items']
            bu = bugun()
            acik = [g for g in gorevler(items) if not g['bitti']]
            gec = [g for g in acik if (gun_coz(g['gun'], bu) or bu) < bu]
            if gec:
                ek_ += f'\nGeciken açık görev: {len(gec)} (en eskisi: {gec[0]["metin"][:50]}).'
            notlar_ = [n for n in _board(items)['notes'] if isinstance(n, dict) and n.get('title') and not re.search(r'\(devam \d+\)\s*$', str(n.get('title')))
                       and not (n.get('categoryId') in _gizli_idler(items) and n.get('categoryId') is not None)]
            if notlar_:
                ek_ += '\nSon notlar: ' + '; '.join(str(n['title'])[:40] for n in notlar_[-8:]) + '.'
        except Exception:
            pass
        ilke = ('\nÇalışma ilkeleri: kullanıcı bir görev/fikir söylerse sormadan kaydet, sonra tek geliştirici soru sor; yeni not açmadan önce ara/notlar ile benzerine bak ve '
                'varsa sonuna ekle; silme ya da metni değiştirme öncesi tek cümle teyit al (silinenler geri dönüşüm kutusuna gider); “bugünümü planla” → planla, onaylarsa plan_uygula; '
                '“fikrimi geliştir” → fikir_gelistir; “bu fikri göreve çevir” → fikri_goreve_cevir; “nasıl gidiyorum / haftayı özetle” → gozden_gecir; çok maddeli listede gorev_toplu; '
                'gün/saat belirsizse makul varsay ve söyle.')
        return '[FİKİR ALANIM — kullanıcının görev/fikir/haftalık program/rutin/günlük/kaynak alanı; araç: fikir_arac]\n' + '\n'.join(satirlar[:12]) + \
               f'\n(Toplam açık görev: {s["acik"]}, fikir: {s["fikir"]}, haftalık blok: {s["blok"]}. "Gizli" kategoridekileri görmezsin.)' + ek_ + ilke
    except Exception:
        return ''
