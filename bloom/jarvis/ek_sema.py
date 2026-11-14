"""BLOOM — şema (diyagram) üretici: metinden SVG.

BLOOM'un sesli anlattığı bir akışı/yapıyı/fikir haritasını Fikir Alanım'ın FİKİRLER panosuna ŞEMA olarak koyabilmesi için. Dış kütüphane yok;
yerleşim ve çizim burada yapılır, çıktı bir SVG'dir (Fikir notunun resmi olarak gömülür; karta tıklayınca tam ekran açılır).

Türler
  akis    akış şeması: Başla/Son (hap), İşlem (yuvarlak kutu), Karar (baklava, "?" ile biten ya da |karar), Veri (paralelkenar), Not.
          Katmanlı yerleşim (en uzun yol), döngüleri ve atlayan okları kenardan dolaştırır. yön: dikey (varsayılan) | yatay
  agac    hiyerarşi / mimari / organizasyon: akış gibi ama kutular (|kutu) ve veritabanı (|db) şekilleriyle
  zihin   zihin haritası: ortada ana fikir, dallar iki yana açılır (girinti: "- dal", "-- alt dal")
  zaman   zaman çizelgesi: "tarih|olay|ayrıntı"

Giriş biçimi (sesli modele kolay, metin):
  düğümler   "Başla|baslat; Veriyi oku; Geçerli mi?; Kaydet; Bitir|son"   (satır ya da ; ile ayrılır, |tür)  — ya da JSON {"nodes":[...],"edges":[...]}
  bağlantılar "Başla -> Veriyi oku; Geçerli mi? -> Kaydet : evet; Geçerli mi? -> Veriyi oku : hayır"   (etiket ya da 1'den başlayan sıra numarası)
             akışta boş bırakılırsa düğümler sırayla bağlanır.
"""

from __future__ import annotations
import base64
import json
import math
import re
import uuid
from xml.sax.saxutils import escape

MAX_DUGUM = 40
MAX_BAG = 90
TURLER = ('akis', 'agac', 'zihin', 'zaman')
TUR_AD = {'akis': 'akış şeması', 'agac': 'hiyerarşi / mimari', 'zihin': 'zihin haritası', 'zaman': 'zaman çizelgesi'}

BG, PANEL, KENAR, YAZI, SOLUK, OK = '#0d1a24', '#13283a', '#3fb8d8', '#e8f6ff', '#8fb3c4', '#7fc6dc'
DAL_RENK = ['#35d0ff', '#ffb454', '#7be08a', '#ff7a90', '#b79bff', '#ffd95e', '#5eead4', '#f59ac2']
KIND_RENK = {'start': '#2f9e6e', 'end': '#c0566a', 'decision': '#d9a441', 'process': '#3fb8d8', 'data': '#8f7be0', 'note': '#7b8da0', 'box': '#3fb8d8', 'db': '#c98a3d'}
KIND_AD = {'baslat': 'start', 'baslangic': 'start', 'basla': 'start', 'start': 'start', 'son': 'end', 'bitis': 'end', 'bitir': 'end', 'end': 'end',
           'karar': 'decision', 'soru': 'decision', 'decision': 'decision', 'islem': 'process', 'adim': 'process', 'surec': 'process', 'process': 'process',
           'veri': 'data', 'girdi': 'data', 'cikti': 'data', 'data': 'data', 'not': 'note', 'nota': 'note', 'kutu': 'box', 'servis': 'box', 'bilesen': 'box',
           'box': 'box', 'veritabani': 'db', 'db': 'db', 'depo': 'db'}


def _fold(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(t or '').replace('İ', 'i').replace('I', 'ı').lower())
    t = ''.join(c for c in t if not unicodedata.combining(c)).replace('ı', 'i')
    return re.sub(r'\s+', ' ', t).strip()


def _kind(ad: str, etiket: str, tur: str) -> str:
    k = KIND_AD.get(_fold(ad))
    if k:
        return k
    f = _fold(etiket)
    if etiket.strip().endswith('?'):
        return 'decision'
    if tur == 'akis':
        if f in ('basla', 'baslangic', 'start', 'baslat'):
            return 'start'
        if f in ('bitir', 'son', 'bitis', 'end', 'bitti'):
            return 'end'
    return 'box' if tur == 'agac' else 'process'


# --------------------------------------------------------------------------- ayrıştırma
def _parcala(metin: str) -> list[str]:
    return [x.strip() for x in re.split(r'[;\n]+', str(metin or '')) if x.strip()]


def coz(tur: str, dugumler: str = '', baglantilar: str = '', yon: str = '') -> dict:
    """Metni şema tanımına çevirir: {'tur','yon','nodes':[{'id','label','detail','kind','depth'}],'edges':[{'a','b','label'}]}. Geçersizse ValueError."""
    tur = _fold(tur) or 'akis'
    tur = {'akis semasi': 'akis', 'akis': 'akis', 'flow': 'akis', 'agac': 'agac', 'hiyerarsi': 'agac', 'mimari': 'agac', 'organizasyon': 'agac',
           'zihin': 'zihin', 'mindmap': 'zihin', 'zihin haritasi': 'zihin', 'zaman': 'zaman', 'zaman cizelgesi': 'zaman', 'timeline': 'zaman'}.get(tur, tur)
    if tur not in TURLER:
        raise ValueError('Şema türü: akis | agac | zihin | zaman.')
    ham = str(dugumler or '').strip()
    nodes: list[dict] = []
    edges: list[dict] = []
    if ham.startswith('{'):
        try:
            d = json.loads(ham)
        except Exception:
            raise ValueError('Düğüm JSON’u okunamadı.')
        for i, n in enumerate(d.get('nodes') or d.get('dugumler') or []):
            lab = str((n.get('label') if isinstance(n, dict) else n) or '').strip()
            if lab:
                nodes.append({'id': str((n.get('id') if isinstance(n, dict) else None) or f'n{i + 1}'), 'label': lab[:60], 'detail': str((n.get('detail') if isinstance(n, dict) else '') or '')[:120],
                              'kind': _kind(str(n.get('kind') or '') if isinstance(n, dict) else '', lab, tur), 'depth': int((n.get('depth') if isinstance(n, dict) else 0) or 0)})
        idx = {n['id']: n for n in nodes}
        for e in d.get('edges') or d.get('baglantilar') or []:
            a, b = str(e.get('from') or e.get('a') or ''), str(e.get('to') or e.get('b') or '')
            if a in idx and b in idx:
                edges.append({'a': a, 'b': b, 'label': str(e.get('label') or '')[:40]})
    else:
        for i, satir in enumerate(_parcala(dugumler)):
            if tur == 'zihin':
                if not satir.strip():
                    continue
                m = re.match(r'^\s*(-*)\s*(.+)$', satir)
                derinlik, metin = len(m.group(1)), m.group(2).strip()
            else:
                derinlik, metin = 0, satir
            parcalar = [p.strip() for p in metin.split('|')]
            etiket = parcalar[0][:60]
            if not etiket:
                continue
            if tur == 'zaman':
                nodes.append({'id': f'n{len(nodes) + 1}', 'label': etiket, 'detail': ' — '.join(parcalar[1:])[:160], 'kind': 'process', 'depth': 0})
            else:
                kind = _kind(parcalar[1] if len(parcalar) > 1 else '', etiket, tur)
                nodes.append({'id': f'n{len(nodes) + 1}', 'label': etiket, 'detail': '', 'kind': kind, 'depth': derinlik})
    if len(nodes) < 2:
        raise ValueError('Şema için en az 2 düğüm gerekir.')
    if len(nodes) > MAX_DUGUM:
        raise ValueError(f'En çok {MAX_DUGUM} düğüm çizebilirim; konuyu iki şemaya böl.')
    # ids benzersiz
    gor = set()
    for n in nodes:
        while n['id'] in gor:
            n['id'] += 'x'
        gor.add(n['id'])

    def bul(ref: str):
        r = ref.strip()
        if re.fullmatch(r'\d+', r) and 1 <= int(r) <= len(nodes):
            return nodes[int(r) - 1]['id']
        f = _fold(r)
        for n in nodes:
            if _fold(n['label']) == f or n['id'] == r:
                return n['id']
        cand = [n for n in nodes if f and f in _fold(n['label'])]
        return cand[0]['id'] if len(cand) == 1 else None

    if not edges:
        for satir in _parcala(baglantilar):
            m = re.match(r'^(.+?)\s*(?:-+>|→|=>)\s*(.+?)(?:\s*[:：]\s*(.+))?$', satir)
            if not m:
                continue
            a, b = bul(m.group(1)), bul(m.group(2))
            if a and b and a != b:
                edges.append({'a': a, 'b': b, 'label': (m.group(3) or '').strip()[:40]})
            elif not (a and b):
                raise ValueError(f'Bağlantıdaki ad şemada yok: “{satir[:60]}” (düğüm adlarıyla ya da sıra numarasıyla yaz).')
    if tur == 'zihin' and not edges:
        yig = []
        for n in nodes:
            while yig and yig[-1]['depth'] >= n['depth'] and len(yig) > 0 and n is not nodes[0]:
                yig.pop()
            if yig:
                edges.append({'a': yig[-1]['id'], 'b': n['id'], 'label': ''})
            elif n is not nodes[0]:
                edges.append({'a': nodes[0]['id'], 'b': n['id'], 'label': ''})
            yig.append(n)
    if tur == 'akis' and not edges:
        edges = [{'a': nodes[i]['id'], 'b': nodes[i + 1]['id'], 'label': ''} for i in range(len(nodes) - 1)]
    if tur == 'agac' and not edges:
        raise ValueError('Hiyerarşi için bağlantılar gerekir (ör. “Sunucu -> Veritabanı”).')
    if len(edges) > MAX_BAG:
        raise ValueError('Çok fazla bağlantı.')
    gorulen, tekil = set(), []
    for e in edges:
        k = (e['a'], e['b'], e['label'])
        if k not in gorulen:
            gorulen.add(k)
            tekil.append(e)
    return {'tur': tur, 'yon': 'yatay' if _fold(yon) in ('yatay', 'soldan saga', 'lr') else 'dikey', 'nodes': nodes, 'edges': tekil}


# --------------------------------------------------------------------------- ölçü ve çizim yardımcıları
def _sar(metin: str, genislik: int) -> list[str]:
    kel, satirlar, cur = str(metin).split(), [], ''
    for k in kel:
        while len(k) > genislik:
            if cur:
                satirlar.append(cur)
                cur = ''
            satirlar.append(k[:genislik])
            k = k[genislik:]
        if len(cur) + len(k) + (1 if cur else 0) <= genislik:
            cur = (cur + ' ' + k).strip()
        else:
            satirlar.append(cur)
            cur = k
    if cur:
        satirlar.append(cur)
    return satirlar[:5] or ['']


FONT = 15
CH = 8.1          # ortalama karakter genişliği (px) ~15 px Segoe UI


def _olc(n: dict, tur: str) -> None:
    satir = _sar(n['label'], 20 if tur != 'zihin' else 22)
    en = max(len(s) for s in satir)
    w = max(96, min(250, en * CH + 38))
    h = 24 + 20 * len(satir)
    if n['kind'] == 'decision':
        w, h = w * 1.35 + 12, h * 1.45 + 6
    elif n['kind'] == 'db':
        h += 14
    n['lines'], n['w'], n['h'] = satir, w, h


def _rect_kenar(cx, cy, w, h, tx, ty):
    """Merkezden (tx,ty) yönüne giden doğrunun dikdörtgenle kesişimi."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (w / 2) / abs(dx) if dx else 1e9
    sy = (h / 2) / abs(dy) if dy else 1e9
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _baklava_kenar(cx, cy, w, h, tx, ty):
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    s = 1 / (abs(dx) / (w / 2) + abs(dy) / (h / 2))
    return cx + dx * s, cy + dy * s


def _kenar_nok(n, tx, ty):
    f = _baklava_kenar if n['kind'] == 'decision' else _rect_kenar
    return f(n['x'], n['y'], n['w'], n['h'], tx, ty)


# --------------------------------------------------------------------------- katmanlı yerleşim (akis, agac)
def _katmanla(nodes, edges):
    ids = [n['id'] for n in nodes]
    out = {i: [] for i in ids}
    inn = {i: [] for i in ids}
    for e in edges:
        out[e['a']].append(e['b'])
        inn[e['b']].append(e['a'])
    # döngüleri kır: DFS'te geri kenarları işaretle
    geri = set()
    durum = {}

    def dfs(u):
        durum[u] = 1
        for v in out[u]:
            if durum.get(v) == 1:
                geri.add((u, v))
            elif v not in durum:
                dfs(v)
        durum[u] = 2
    kokler = [i for i in ids if not inn[i]] or [ids[0]]
    for r in kokler + ids:
        if r not in durum:
            dfs(r)
    ileri = [(e['a'], e['b']) for e in edges if (e['a'], e['b']) not in geri]
    rank = {i: 0 for i in ids}
    for _ in range(len(ids) + 1):
        degisti = False
        for a, b in ileri:
            if rank[b] < rank[a] + 1:
                rank[b] = rank[a] + 1
                degisti = True
        if not degisti:
            break
    return rank, geri


def _katman_yerlesim(spec):
    """Katmanlı (Sugiyama tarzı) yerleşim. Birden çok katmanı atlayan ve geri giden oklara görünmez ARA DÜĞÜMLER konur: oklar düğümlerin
    üstünden geçmez, kendi yollarını bulur. Döner: rank, geri, idx, zincir{kenar_no: [ara düğümler]}, tüm düğümler (ara dahil)."""
    nodes, edges, yon = spec['nodes'], spec['edges'], spec['yon']
    for n in nodes:
        _olc(n, spec['tur'])
    rank, geri = _katmanla(nodes, edges)
    idx = {n['id']: n for n in nodes}
    tum = list(nodes)
    zincir = {}
    for k, e in enumerate(edges):
        a_, b_ = e['a'], e['b']
        if (a_, b_) in geri:
            a_, b_ = b_, a_
        lo, hi = rank[a_], rank[b_]
        if lo > hi:
            lo, hi, a_, b_ = hi, lo, b_, a_
        ara = []
        for r in range(lo + 1, hi):
            d = {'id': f'_d{k}_{r}', 'dummy': True, 'kind': 'dummy', 'w': 12.0, 'h': 12.0, 'label': ''}
            idx[d['id']] = d
            rank[d['id']] = r
            ara.append(d)
            tum.append(d)
        zincir[k] = (a_, ara, b_)
    kat = {}
    for n in tum:
        kat.setdefault(rank[n['id']], []).append(n)
    komsu = {n['id']: [] for n in tum}
    for k, (a_, ara, b_) in zincir.items():
        yol = [a_] + [d['id'] for d in ara] + [b_]
        for u, v in zip(yol, yol[1:]):
            komsu[u].append(v)
            komsu[v].append(u)
    pos = {}
    for r in sorted(kat):
        for i, n in enumerate(kat[r]):
            pos[n['id']] = i
    for _ in range(8):                 # barycenter süpürmeleri
        for r in sorted(kat)[1:] + sorted(kat, reverse=True)[1:]:
            ort = {}
            for n in kat[r]:
                kom = [pos[v] for v in komsu[n['id']] if rank[v] != r]
                ort[n['id']] = sum(kom) / len(kom) if kom else pos[n['id']]
            kat[r].sort(key=lambda n: ort[n['id']])
            for i, n in enumerate(kat[r]):
                pos[n['id']] = i
    dikey = yon == 'dikey'
    BOSLUK_CAPRAZ, BOSLUK_ANA = 40, 78

    def capraz(n):
        return n['w'] if dikey else n['h']

    def ana(n):
        return n['h'] if dikey else n['w']
    genislik = {r: sum(capraz(n) for n in kat[r]) + BOSLUK_CAPRAZ * (len(kat[r]) - 1) for r in kat}
    en = max(genislik.values())
    y = 0.0
    for r in sorted(kat):
        kalin = max(ana(n) for n in kat[r])
        x = (en - genislik[r]) / 2
        for n in kat[r]:
            c = x + capraz(n) / 2
            m = y + kalin / 2
            n['x'], n['y'] = (c, m) if dikey else (m, c)
            x += capraz(n) + BOSLUK_CAPRAZ
        y += kalin + BOSLUK_ANA
    return rank, geri, idx, zincir, tum


# --------------------------------------------------------------------------- SVG çizim
def _metin_svg(satirlar, cx, cy, renk=YAZI, boyut=FONT, kalin=False) -> str:
    n = len(satirlar)
    y0 = cy - (n - 1) * (boyut + 3) / 2
    parca = []
    for i, s in enumerate(satirlar):
        parca.append(f'<text x="{cx:.1f}" y="{y0 + i * (boyut + 3):.1f}" text-anchor="middle" dominant-baseline="central" fill="{renk}" font-size="{boyut}"'
                     + (' font-weight="600"' if kalin else '') + f'>{escape(s)}</text>')
    return ''.join(parca)


def _sekil(n, renk) -> str:
    x, y, w, h = n['x'], n['y'], n['w'], n['h']
    k = n['kind']
    dolgu = f'fill="{PANEL}" stroke="{renk}" stroke-width="2"'
    if k == 'decision':
        s = f'<polygon points="{x:.1f},{y - h / 2:.1f} {x + w / 2:.1f},{y:.1f} {x:.1f},{y + h / 2:.1f} {x - w / 2:.1f},{y:.1f}" {dolgu}/>'
    elif k in ('start', 'end'):
        s = f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{h / 2:.1f}" fill="{renk}" fill-opacity=".22" stroke="{renk}" stroke-width="2"/>'
    elif k == 'data':
        sk = 14
        s = f'<polygon points="{x - w / 2 + sk:.1f},{y - h / 2:.1f} {x + w / 2:.1f},{y - h / 2:.1f} {x + w / 2 - sk:.1f},{y + h / 2:.1f} {x - w / 2:.1f},{y + h / 2:.1f}" {dolgu}/>'
    elif k == 'db':
        ry = 9
        s = (f'<path d="M{x - w / 2:.1f},{y - h / 2 + ry:.1f} v{h - 2 * ry:.1f} a{w / 2:.1f},{ry} 0 0 0 {w:.1f},0 v{-(h - 2 * ry):.1f} a{w / 2:.1f},{ry} 0 0 0 {-w:.1f},0 z" {dolgu}/>'
             f'<ellipse cx="{x:.1f}" cy="{y - h / 2 + ry:.1f}" rx="{w / 2:.1f}" ry="{ry}" fill="{renk}" fill-opacity=".18" stroke="{renk}" stroke-width="2"/>')
    elif k == 'note':
        s = f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" fill="{PANEL}" stroke="{renk}" stroke-width="1.5" stroke-dasharray="5 4"/>'
    else:
        s = f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{10 if k == "process" else 6}" {dolgu}/>'
    return s


def _egri(noktalar, dikey) -> str:
    """Noktalardan geçen, her noktada ana eksene paralel teğetli S-eğriler zinciri."""
    d = f'M{noktalar[0][0]:.1f},{noktalar[0][1]:.1f}'
    for (x1, y1), (x2, y2) in zip(noktalar, noktalar[1:]):
        if dikey:
            my = (y1 + y2) / 2
            d += f' C{x1:.1f},{my:.1f} {x2:.1f},{my:.1f} {x2:.1f},{y2:.1f}'
        else:
            mx = (x1 + x2) / 2
            d += f' C{mx:.1f},{y1:.1f} {mx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}'
    return d


def _sar_svg(govde: str, w: float, h: float, baslik: str, tur: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" font-family="Segoe UI, Roboto, Arial, sans-serif">'
            f'<title>{escape(baslik)}</title><defs><marker id="ok" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{OK}"/></marker></defs>'
            f'<rect width="{w:.0f}" height="{h:.0f}" rx="16" fill="{BG}"/>{govde}</svg>')


def _cizim_katmanli(spec, baslik: str) -> str:
    rank, geri, idx, zincir, tum = _katman_yerlesim(spec)
    nodes, edges, dikey = spec['nodes'], spec['edges'], spec['yon'] == 'dikey'
    PAD, BAS = 36, 46 if baslik else 0
    minx = min(n['x'] - n['w'] / 2 for n in tum)
    maxx = max(n['x'] + n['w'] / 2 for n in tum)
    miny = min(n['y'] - n['h'] / 2 for n in tum)
    maxy = max(n['y'] + n['h'] / 2 for n in tum)
    for n in tum:
        n['x'] += PAD - minx
        n['y'] += PAD + BAS - miny
    W = maxx - minx + 2 * PAD
    H = maxy - miny + 2 * PAD + BAS
    g = []
    if baslik:
        g.append(f'<text x="{PAD}" y="{PAD + 12}" fill="{YAZI}" font-size="19" font-weight="700">{escape(baslik)}</text>')
    yollar, etiketler = [], []
    for k, e in enumerate(edges):
        a_id, ara, b_id = zincir[k]
        a, b = idx[a_id], idx[b_id]
        geri_mi = (e['a'], e['b']) in geri
        # zincir orijinal yönden saklandı mı? geri kenarda a_id/b_id yer değiştirmiş olabilir: çizim yönünü kenarın kendi yönüne göre kur
        dugumler = [a] + ara + [b]
        if e['a'] != a_id:
            dugumler = dugumler[::-1]
        ilk, son = dugumler[0], dugumler[-1]
        ic = dugumler[1:-1]
        p_ilk = _kenar_nok(ilk, *( (dugumler[1]['x'], dugumler[1]['y']) ))
        p_son = _kenar_nok(son, *( (dugumler[-2]['x'], dugumler[-2]['y']) ))
        pts = [p_ilk] + [(d['x'], d['y']) for d in ic] + [p_son]
        yollar.append(f'<path d="{_egri(pts, dikey)}" fill="none" stroke="{OK}" stroke-width="2" marker-end="url(#ok)"' + (' stroke-dasharray="6 4"' if geri_mi else '') + '/>')
        if e['label']:
            if ic:
                lx, ly = ic[len(ic) // 2]['x'], ic[len(ic) // 2]['y']
            else:
                lx, ly = (p_ilk[0] + p_son[0]) / 2, (p_ilk[1] + p_son[1]) / 2
            tw = len(e['label']) * 7.2 + 12
            etiketler.append(f'<rect x="{lx - tw / 2:.1f}" y="{ly - 11:.1f}" width="{tw:.1f}" height="20" rx="6" fill="{BG}" stroke="{KENAR}" stroke-opacity=".5"/>'
                             f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" dominant-baseline="central" fill="{YAZI}" font-size="13">{escape(e["label"])}</text>')
    g.extend(yollar)
    for n in nodes:
        renk = KIND_RENK.get(n['kind'], KENAR)
        g.append(_sekil(n, renk))
        g.append(_metin_svg(n['lines'], n['x'], n['y'], YAZI, FONT, n['kind'] in ('start', 'end')))
    g.extend(etiketler)
    return _sar_svg(''.join(g), W, H, baslik, spec['tur'])


# --------------------------------------------------------------------------- zihin haritası
def _cizim_zihin(spec, baslik: str) -> str:
    nodes, edges = spec['nodes'], spec['edges']
    idx = {n['id']: n for n in nodes}
    cocuk = {n['id']: [] for n in nodes}
    ebeveyn = {}
    for e in edges:
        if e['b'] not in ebeveyn and e['a'] != e['b']:
            ebeveyn[e['b']] = e['a']
            cocuk[e['a']].append(e['b'])
    kok = nodes[0]['id']
    for n in nodes:
        _olc(n, 'zihin')
    yaprak = {}

    def say(u, goruldu=()):
        if u in goruldu:
            return 1
        c = cocuk[u]
        yaprak[u] = max(1, sum(say(v, goruldu + (u,)) for v in c)) if c else 1
        return yaprak[u]
    say(kok)
    sol, sag = [], []
    ts = tl = 0
    for ch in cocuk[kok]:
        if ts <= tl:
            sag.append(ch)
            ts += yaprak[ch]
        else:
            sol.append(ch)
            tl += yaprak[ch]
    SLOT = 64
    konum = {kok: (0.0, 0.0)}
    dal = {kok: -1}

    def yerles(grup, yon):
        toplam = sum(yaprak[c] for c in grup)
        y = -toplam * SLOT / 2
        for ch in grup:
            span = yaprak[ch] * SLOT
            alt(ch, yon, 1, y, y + span, kok, grup.index(ch) + (0 if yon > 0 else len(sag)))
            y += span

    def alt(u, yon, derin, y0, y1, ebv, dalno):
        dal[u] = dalno
        # sütun x: ebeveynin sağ/sol kenarı + boşluk
        px, py = konum[ebv]
        pw = idx[ebv]['w']
        x = px + yon * (pw / 2 + 64 + idx[u]['w'] / 2)
        konum[u] = (x, (y0 + y1) / 2)
        c = [v for v in cocuk[u] if v not in konum]
        if c:
            tot = sum(yaprak[v] for v in c) * SLOT
            yy = (y0 + y1) / 2 - tot / 2
            for v in c:
                sp = yaprak[v] * SLOT
                alt(v, yon, derin + 1, yy, yy + sp, u, dalno)
                yy += sp
    yerles(sag, 1)
    yerles(sol, -1)
    for n in nodes:
        if n['id'] not in konum:       # bağlantısız düğüm
            konum[n['id']] = (0.0, 0.0)
    ek = 0
    for n in nodes:
        if n['id'] not in dal:
            dal[n['id']] = 0
    minx = min(konum[n['id']][0] - n['w'] / 2 for n in nodes)
    maxx = max(konum[n['id']][0] + n['w'] / 2 for n in nodes)
    miny = min(konum[n['id']][1] - n['h'] / 2 for n in nodes)
    maxy = max(konum[n['id']][1] + n['h'] / 2 for n in nodes)
    PAD, BAS = 36, 46 if baslik else 0
    for n in nodes:
        n['x'] = konum[n['id']][0] + PAD - minx
        n['y'] = konum[n['id']][1] + PAD + BAS - miny
    W, H = maxx - minx + 2 * PAD, maxy - miny + 2 * PAD + BAS
    g = []
    if baslik:
        g.append(f'<text x="{PAD}" y="{PAD + 12}" fill="{YAZI}" font-size="19" font-weight="700">{escape(baslik)}</text>')
    for e in edges:
        a, b = idx[e['a']], idx[e['b']]
        renk = DAL_RENK[dal[b['id']] % len(DAL_RENK)] if dal[b['id']] >= 0 else KENAR
        yon = 1 if b['x'] >= a['x'] else -1
        x1, y1 = a['x'] + yon * (a['w'] / 2 + (6 if a['id'] == kok else 0)), a['y']
        x2, y2 = b['x'] - yon * b['w'] / 2, b['y']
        mx = (x1 + x2) / 2
        g.append(f'<path d="M{x1:.1f},{y1:.1f} C{mx:.1f},{y1:.1f} {mx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{renk}" stroke-width="2.4" stroke-opacity=".85"/>')
    for n in nodes:
        if n['id'] == kok:
            g.append(f'<rect x="{n["x"] - n["w"] / 2 - 6:.1f}" y="{n["y"] - n["h"] / 2 - 4:.1f}" width="{n["w"] + 12:.1f}" height="{n["h"] + 8:.1f}" rx="{(n["h"] + 8) / 2:.1f}" fill="{KENAR}" fill-opacity=".25" stroke="{KENAR}" stroke-width="2.5"/>')
            g.append(_metin_svg(n['lines'], n['x'], n['y'], YAZI, 17, True))
        else:
            renk = DAL_RENK[dal[n['id']] % len(DAL_RENK)] if dal[n['id']] >= 0 else KENAR
            g.append(f'<rect x="{n["x"] - n["w"] / 2:.1f}" y="{n["y"] - n["h"] / 2:.1f}" width="{n["w"]:.1f}" height="{n["h"]:.1f}" rx="10" fill="{renk}" fill-opacity=".14" stroke="{renk}" stroke-width="1.8"/>')
            g.append(_metin_svg(n['lines'], n['x'], n['y'], YAZI, FONT))
    return _sar_svg(''.join(g), W, H, baslik, 'zihin')


# --------------------------------------------------------------------------- zaman çizelgesi
def _cizim_zaman(spec, baslik: str) -> str:
    nodes = spec['nodes']
    PAD, BAS = 36, 46 if baslik else 0
    SOL, SATIR = 170, 0
    g = []
    y = PAD + BAS + 8
    cizgi_y0 = y
    satirlar = []
    for n in nodes:
        detay = _sar(n['detail'], 46) if n['detail'] else []
        h = max(48, 28 + 20 * len(detay))
        satirlar.append((n, detay, y, h))
        y += h + 14
    cizgi_y1 = y - 14 - satirlar[-1][3] / 2
    W = PAD * 2 + SOL + 480
    H = y + PAD - 14
    if baslik:
        g.append(f'<text x="{PAD}" y="{PAD + 12}" fill="{YAZI}" font-size="19" font-weight="700">{escape(baslik)}</text>')
    g.append(f'<line x1="{PAD + SOL}" y1="{cizgi_y0 + 22}" x2="{PAD + SOL}" y2="{satirlar[-1][2] + 22}" stroke="{KENAR}" stroke-width="3" stroke-opacity=".6"/>')
    for i, (n, detay, y0, h) in enumerate(satirlar):
        renk = DAL_RENK[i % len(DAL_RENK)]
        cy = y0 + 22
        g.append(f'<circle cx="{PAD + SOL}" cy="{cy}" r="9" fill="{BG}" stroke="{renk}" stroke-width="3"/><circle cx="{PAD + SOL}" cy="{cy}" r="3.5" fill="{renk}"/>')
        g.append(f'<text x="{PAD + SOL - 22}" y="{cy}" text-anchor="end" dominant-baseline="central" fill="{renk}" font-size="16" font-weight="700">{escape(n["label"])}</text>')
        for k, s in enumerate(detay):
            g.append(f'<text x="{PAD + SOL + 24}" y="{cy + (k) * 20:.0f}" dominant-baseline="central" fill="{YAZI if k == 0 else SOLUK}" font-size="15">{escape(s)}</text>')
        if not detay:
            g.append(f'<text x="{PAD + SOL + 24}" y="{cy}" dominant-baseline="central" fill="{SOLUK}" font-size="15">·</text>')
    return _sar_svg(''.join(g), W, H, baslik, 'zaman')


# --------------------------------------------------------------------------- dış API
def svg_uret(spec: dict, baslik: str = '') -> str:
    t = spec['tur']
    if t == 'zihin':
        return _cizim_zihin(spec, baslik)
    if t == 'zaman':
        return _cizim_zaman(spec, baslik)
    return _cizim_katmanli(spec, baslik)


def veri_url(svg: str) -> str:
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode('utf-8')).decode('ascii')


def resim(spec: dict, baslik: str = '') -> dict:
    """Fikir notunun `images` öğesi: {'id','data','w','h','name'}."""
    svg = svg_uret(spec, baslik)
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    return {'id': 'sema-' + uuid.uuid4().hex[:8], 'data': veri_url(svg), 'w': int(m.group(1)), 'h': int(m.group(2)), 'name': (baslik or 'şema')[:60] + '.svg'}


def ozet_metin(spec: dict, baslik: str = '') -> str:
    """Notun metni: şemanın düz yazı karşılığı (arama, sesli okuma, görme engelli erişimi için)."""
    nodes = {n['id']: n for n in spec['nodes']}
    s = [f'ŞEMA ({TUR_AD.get(spec["tur"], spec["tur"])}) — {baslik}'.strip(' —'), '', 'ADIMLAR / ÖĞELER']
    if spec['tur'] == 'zihin':
        cocuk = {}
        for e in spec['edges']:
            cocuk.setdefault(e['a'], []).append(e['b'])

        def yaz(u, d):
            s.append('  ' * d + ('- ' if d else '') + nodes[u]['label'])
            for v in cocuk.get(u, []):
                yaz(v, d + 1)
        yaz(spec['nodes'][0]['id'], 0)
        return '\n'.join(s)
    for i, n in enumerate(spec['nodes'], 1):
        s.append(f'{i}. {n["label"]}' + (f' — {n["detail"]}' if n.get('detail') else '') + (' (karar)' if n['kind'] == 'decision' else ''))
    if spec['edges'] and spec['tur'] != 'zaman':
        s += ['', 'BAĞLANTILAR']
        for e in spec['edges']:
            s.append(f'- {nodes[e["a"]]["label"]} → {nodes[e["b"]]["label"]}' + (f' ({e["label"]})' if e.get('label') else ''))
    return '\n'.join(s)


# --------------------------------------------------------------------------- düzenleme (sidecar'daki şemayı değiştir)
def _temiz(t: str) -> str:
    return re.sub(r'[;|\n\r]+', ' ', str(t or '')).strip()


def metne(spec: dict, cikar=()) -> tuple[str, str]:
    """Şemayı tekrar (düğümler, bağlantılar) metnine çevirir. Bağlantılar 1'den başlayan SIRA NUMARASIYLA yazılır (aynı adlı düğümler karışmaz).
    `cikar`: silinecek düğüm adları. Akışta silinen düğümün tek girişi ve tek çıkışı varsa onarılır (önceki → sonraki).
    Zihin haritasında düğümle birlikte alt dalları da gider."""
    nodes = [dict(n) for n in spec['nodes']]
    edges = [dict(e) for e in spec['edges']]
    sil = set()
    for ad in cikar or ():
        f = _fold(ad)
        if not f:
            continue
        hit = [n for n in nodes if _fold(n['label']) == f] or [n for n in nodes if f in _fold(n['label'])]
        if len(hit) > 1 and not all(_fold(h['label']) == f for h in hit):
            raise ValueError(f'“{ad}” birden çok düğüme uyuyor: ' + '; '.join(h['label'] for h in hit[:5]))
        if not hit:
            raise ValueError(f'Şemada “{ad}” adlı bir düğüm yok.')
        for h in hit[:1]:
            sil.add(h['id'])
            if spec['tur'] == 'zihin':
                i = nodes.index(h)
                for sonraki in nodes[i + 1:]:
                    if sonraki['depth'] > h['depth']:
                        sil.add(sonraki['id'])
                    else:
                        break
    if sil:
        if spec['tur'] in ('akis', 'agac'):
            for u in list(sil):
                gel = [e for e in edges if e['b'] == u and e['a'] not in sil]
                git = [e for e in edges if e['a'] == u and e['b'] not in sil]
                if len(gel) == 1 and len(git) == 1:
                    edges.append({'a': gel[0]['a'], 'b': git[0]['b'], 'label': gel[0].get('label') or git[0].get('label') or ''})
        nodes = [n for n in nodes if n['id'] not in sil]
        edges = [e for e in edges if e['a'] not in sil and e['b'] not in sil]
    no = {n['id']: i for i, n in enumerate(nodes, 1)}
    if spec['tur'] == 'zihin':
        d = ';'.join(('-' * n['depth'] + ' ' if n['depth'] else '') + _temiz(n['label']) for n in nodes)
        return d, ''
    if spec['tur'] == 'zaman':
        return ';'.join(_temiz(n['label']) + ('|' + _temiz(n['detail']) if n.get('detail') else '') for n in nodes), ''
    ters = {v: k for k, v in KIND_AD.items() if k in ('baslat', 'son', 'karar', 'islem', 'veri', 'not', 'kutu', 'db')}
    d = ';'.join(_temiz(n['label']) + '|' + ters.get(n['kind'], 'islem') for n in nodes)
    b = ';'.join(f'{no[e["a"]]} -> {no[e["b"]]}' + (f' : {_temiz(e["label"])}' if e.get('label') else '') for e in edges if e['a'] in no and e['b'] in no)
    return d, b


def guncelle(spec: dict, ek_dugum: str = '', ek_bag: str = '', cikar=(), yon: str = '') -> dict:
    """Var olan şemaya düğüm/bağlantı ekler, düğüm çıkarır. Yeni bağlantılar düğüm adıyla ya da (birleşik listedeki) sıra numarasıyla yazılır."""
    d, b = metne(spec, cikar)
    ilk = len(_parcala(d))
    if ek_dugum:
        d = d + (';' if d else '') + str(ek_dugum)
    if ek_bag:
        b = b + (';' if b else '') + str(ek_bag)
    elif spec['tur'] == 'akis' and ek_dugum and not b:
        b = ''
    yeni = coz(spec['tur'], d, b, yon or spec['yon'])
    if spec['tur'] == 'zaman' or spec['tur'] == 'zihin':
        return yeni
    bagli = {e['a'] for e in yeni['edges']} | {e['b'] for e in yeni['edges']}
    yeni['bagsiz'] = [n['label'] for n in yeni['nodes'][ilk:] if n['id'] not in bagli]
    return yeni
