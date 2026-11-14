"""BLOOM — Fikir Alanım yetkinliği (genişletilmiş `fikir` aracı).

Eskiden BLOOM Fikir Alanım'da yalnızca görev ekleyip bitirebiliyor, not ekleyebiliyor ve haftalık bloğa kayıt koyabiliyordu. Kullanıcı bu alanla
bol bol çalışacağı için artık Fikir Alanım'ın TÜM bölümlerini yönetir:

  NOTLAR      not_duzenle · not_sil (geri dönüşüm kutusuna) · etiketle · sabitle · baglan · benzer · fikir_gelistir · fikri_goreve_cevir · notlar
  GÖREVLER    gorev_toplu · geciken · geciken_tasi · gorev_kategori
  HAFTA       hafta_oku · hafta_duzenle · hafta_sil · bos_zaman · planla · plan_uygula
  RUTİNLER    rutin_oku · rutin_ekle · rutin_yap · rutin_sil
  GÜNLÜK      gunluk_oku · gunluk_yaz
  KAYNAKLAR   kaynak_ekle · kaynak_ara
  KATEGORİ    kategoriler · kategori_ekle
  ŞEMA        sema_ekle · sema_guncelle · sema_oku (Fikirler panosuna diyagram: akış/hiyerarşi/zihin haritası/zaman çizelgesi; ek_sema.py)
  GÖZDEN GEÇİR  gozden_gecir (bugün / hafta)

Veriye yalnızca `ek_fikir.duzenle` üzerinden yazar (kilitli, 3'lü birleştirmeyle sayfadaki elle düzenlemeyi ezmez). Silinenler Fikir'in geri
dönüşüm kutusuna gider; metin değişiklikleri eski sürümü kutuya bırakır. "Gizli" kategori yapay zekâya hiç görünmez.
Her işlev (a: dict) -> str döner; ek_fikir.arac bu modüle devreder.
"""

from __future__ import annotations
import datetime as dt
import json
import re
import time
import uuid
from . import ek_fikir as F
from .log import log

KEY_ROUTINE = 'panel.v3.routine'
KEY_RESOURCES = 'fikir.resources.v1'
KEY_JOURNAL = 'fikir.journal.v1'
KEY_SEMA = 'fikir.sema.v1'          # not_id -> şema tanımı (düzenlenebilsin diye); sayfa bilmez, BLOOM kullanır
SEMA_KATEGORI = 'Şemalar'
CALISMA = ('09:00', '18:00')
VARSAYILAN_DK = 45
ARA_DK = 10
ONCELIK_SIRA = {'high': 0, 'important': 1, 'normal': 2}
ISLEMLER = ('not_oku', 'not_duzenle', 'not_sil', 'etiketle', 'sabitle', 'baglan', 'benzer', 'fikir_gelistir', 'fikri_goreve_cevir', 'notlar',
            'gorev_toplu', 'geciken', 'geciken_tasi', 'gorev_kategori',
            'hafta_oku', 'hafta_duzenle', 'hafta_sil', 'bos_zaman', 'planla', 'plan_uygula',
            'rutin_oku', 'rutin_ekle', 'rutin_yap', 'rutin_sil', 'gunluk_oku', 'gunluk_yaz', 'kaynak_ekle', 'kaynak_ara',
            'kategoriler', 'kategori_ekle', 'gozden_gecir', 'sema_ekle', 'sema_guncelle', 'sema_oku')


def _ek():
    from . import ek
    return ek


# --------------------------------------------------------------------------- ortak
def _s(a: dict, *anahtarlar) -> str:
    for k in anahtarlar:
        v = a.get(k)
        if v not in (None, ''):
            return str(v).strip()
    return ''


def _tarih_anahtari(d: dt.date | None = None) -> str:
    return (d or F.bugun()).isoformat()


def _gorunur_notlar(items: dict) -> list[dict]:
    board = F._board(items)
    gizli = F._gizli_idler(items)
    return [n for n in board['notes'] if isinstance(n, dict) and not (n.get('categoryId') in gizli and n.get('categoryId') is not None)]


def _not_bul(items: dict, ad: str):
    """(not|None, adaylar[başlıklar]). Önce başlık eşleşmesi; olmazsa başlık/metinde TÜM sözcükleri içeren TEK not."""
    ad = ' '.join(str(ad or '').split())
    if not ad:
        return None, []
    board = F._board(items)
    gizli = F._gizli_idler(items)
    for n in board['notes']:
        if isinstance(n, dict) and str(n.get('id')) == ad:
            return n, []
    n = F._not_eslestir(board['notes'], gizli, ad)
    if n is not None:
        return n, []
    toks = [t for t in F._fold(ad).split() if len(t) >= 3]
    adaylar = []
    for q in _gorunur_notlar(items):
        f = F._fold(str(q.get('title') or '') + ' ' + str(q.get('text') or ''))
        if toks and all(t in f for t in toks) and not re.search(r'\(devam \d+\)\s*$', str(q.get('title') or '')):
            adaylar.append(q)
    if len(adaylar) == 1:
        return adaylar[0], []
    return None, [str(q.get('title') or ' '.join(str(q.get('text') or '').split()[:6])) for q in adaylar[:6]]


def _bulunamadi(ad: str, adaylar: list[str]) -> str:
    if adaylar:
        return f'“{ad}” birden çok nota uyuyor: ' + '; '.join(f'“{x}”' for x in adaylar) + '. Hangisi?'
    return f'“{ad}” adlı bir not bulamadım (notlar işlemiyle başlıklara bakabilirsin).'


def _cop_kutusu(items: dict, tur: str, baslik: str, veri: dict) -> None:
    kutu = F._json_oku(items, F.KEY_TRASH, [])
    kutu = kutu if isinstance(kutu, list) else []
    kutu.append({'id': F._yeni_id(), 'kind': tur, 'title': str(baslik)[:140], 'deletedAt': dt.datetime.utcnow().isoformat() + 'Z', 'data': veri})
    items[F.KEY_TRASH] = json.dumps(kutu[-200:], ensure_ascii=False)


def _kisa(t: str, n: int = 140) -> str:
    t = ' '.join(str(t or '').split())
    return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + '…'


def _kat_id(items: dict, ad: str):
    return F._kategori_bul(items, ad) if ad else None


def _liste_metni(x) -> list[str]:
    if isinstance(x, list):
        return [str(e).strip() for e in x if str(e).strip()]
    return [e.strip() for e in re.split(r'[,;\n]+', str(x or '')) if e.strip()]


# --------------------------------------------------------------------------- NOTLAR
def notlar(a: dict) -> str:
    items = F.snapshot_oku()['items']
    liste = _gorunur_notlar(items)
    if not liste:
        return 'Fikir panosunda not yok.'
    sorgu = F._fold(_s(a, 'sorgu', 'kategori'))
    satir = []
    for n in liste:
        if re.search(r'\(devam \d+\)\s*$', str(n.get('title') or '')):
            continue
        kat = F._kategori_adi(items, n.get('categoryId'))
        etk = ', '.join(n.get('tags') or [])
        if sorgu and sorgu not in F._fold(f'{n.get("title", "")} {kat} {etk} {n.get("text", "")}'):
            continue
        ad = str(n.get('title') or '') or ' '.join(str(n.get('text') or '').split()[:6])
        satir.append(f'- {"📌 " if n.get("pinned") else ""}{ad}' + (f' [{kat}]' if kat else '') + (f' #{etk.replace(", ", " #")}' if etk else '')
                     + f' ({len(str(n.get("text") or ""))} kr)' + ({'high': ' ❗', 'important': ' ⭑'}.get(n.get('priority'), '')))
    return (f'{len(satir)} not' + (f' (“{sorgu}” için)' if sorgu else '') + ':\n' + '\n'.join(satir[:60])) if satir else 'Buna uyan not yok.'


def not_duzenle(a: dict) -> str:
    yeni_baslik, yeni_metin = _s(a, 'yeni_baslik'), str(a.get('yeni_metin') or '').strip()
    kategori, oncelik = _s(a, 'kategori'), _s(a, 'oncelik')
    if not (yeni_baslik or yeni_metin or kategori or oncelik):
        return 'Neyi değiştireceğini söyle: yeni_baslik, yeni_metin, kategori ya da oncelik. (Sonuna eklemek için nota_ekle.)'

    def ne(n, items, board):
        degisen = []
        if kategori:
            kid = _kat_id(items, kategori)
            if kid is None:
                raise ValueError(f'“{kategori}” adlı bir kategori yok (kategoriler işlemine bak ya da kategori_ekle).')
            n['categoryId'] = kid
            degisen.append(f'kategori: {kategori}')
        if oncelik in F.ONCELIK:
            n['priority'] = oncelik
            degisen.append(f'öncelik: {oncelik}')
        if yeni_metin:
            if len(yeni_metin) > F.NOT_MAX:
                raise ValueError(f'Yeni metin {len(yeni_metin)} karakter; üst sınır {F.NOT_MAX}. Sonuna eklemek için nota_ekle kullan.')
            _cop_kutusu(items, 'note', f'{n.get("title") or "Not"} (eski sürüm)', {'note': dict(n), 'links': []})
            n['text'] = yeni_metin
            if len(yeni_metin) > 600:
                n['size'] = 'large'
            degisen.append('metin (eski sürüm geri dönüşüm kutusunda)')
        if yeni_baslik:
            n['title'] = yeni_baslik[:80]
            degisen.append(f'başlık: {yeni_baslik[:80]}')
        return f'“{n.get("title") or "Not"}” güncellendi — ' + ', '.join(degisen) + '.'
    return _not_degistir(a, ne)


def not_sil(a: dict) -> str:
    ad = _s(a, 'baslik', 'metin')
    sonuc = []

    def fn(items):
        board = F._board(items)
        gizli = F._gizli_idler(items)
        n = None
        for q in board['notes']:
            if isinstance(q, dict) and str(q.get('id')) == ad:
                n = q
        if n is None:
            n = F._not_eslestir(board['notes'], gizli, ad)
        if n is None:
            _, adaylar = _not_bul(items, ad)
            sonuc.append(('yok', adaylar))
            return
        kimlik = n.get('id')
        silinen_baglar = [l for l in board.get('links', []) if isinstance(l, dict) and (l.get('from') == kimlik or l.get('to') == kimlik)]
        baslik = n.get('title') or ' '.join(str(n.get('text') or '').split()[:6]) or 'Adsız fikir notu'
        # "(devam N)" parçaları ana notla birlikte gider
        parcalar = [q for q in board['notes'] if isinstance(q, dict) and str(q.get('title') or '').startswith(f'{n.get("title")} (devam')] if n.get('title') else []
        for q in [n] + parcalar:
            qb = [l for l in board.get('links', []) if isinstance(l, dict) and (l.get('from') == q.get('id') or l.get('to') == q.get('id'))]
            _cop_kutusu(items, 'note', q.get('title') or baslik, {'note': q, 'links': qb})
        ids = {q.get('id') for q in [n] + parcalar}
        board['notes'] = [q for q in board['notes'] if not (isinstance(q, dict) and q.get('id') in ids)]
        board['links'] = [l for l in board.get('links', []) if not (isinstance(l, dict) and (l.get('from') in ids or l.get('to') in ids))]
        items[F.KEY_BOARD] = json.dumps(board, ensure_ascii=False)
        sonuc.append(('ok', str(baslik), len(parcalar), len(silinen_baglar)))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', [])
    if d[0] == 'ok':
        return f'“{d[1]}” notu silindi (geri dönüşüm kutusunda; oradan geri alınabilir)' + (f', {d[2]} devam parçasıyla birlikte' if d[2] else '') + '.'
    return _bulunamadi(ad, d[1])


def _not_degistir(a: dict, ne) -> str:
    """Tek bir notu bulup `ne(n, items)` ile değiştirir; ne() bir açıklama döner."""
    ad = _s(a, 'baslik', 'metin')
    sonuc = []

    def fn(items):
        board = F._board(items)
        gizli = F._gizli_idler(items)
        n = None
        for q in board['notes']:
            if isinstance(q, dict) and str(q.get('id')) == ad:
                n = q
        if n is None:
            n = F._not_eslestir(board['notes'], gizli, ad)
        if n is None:
            _, adaylar = _not_bul(items, ad)
            sonuc.append(('yok', adaylar))
            return
        try:
            msg = ne(n, items, board)
        except ValueError as exc:
            sonuc.append(('hata', str(exc)))
            return
        items[F.KEY_BOARD] = json.dumps(board, ensure_ascii=False)
        sonuc.append(('ok', msg))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', [])
    return d[1] if d[0] in ('ok', 'hata') else _bulunamadi(ad, d[1])


def etiketle(a: dict) -> str:
    ekle = _liste_metni(a.get('etiketler') or a.get('etiket'))
    if not ekle:
        return 'Hangi etiketler? (etiketler: virgülle).'
    cikar = bool(a.get('cikar') or str(a.get('yeni_metin') or '').lower() in ('cikar', 'çıkar', 'kaldir', 'kaldır'))

    def ne(n, items, board):
        mevcut = [str(t).strip() for t in (n.get('tags') or []) if str(t).strip()]
        yeni = [t.lstrip('#') for t in ekle]
        if cikar:
            f = {F._fold(t) for t in yeni}
            n['tags'] = [t for t in mevcut if F._fold(t) not in f]
        else:
            n['tags'] = (mevcut + [t for t in yeni if F._fold(t) not in {F._fold(m) for m in mevcut}])[:12]
        return f'“{n.get("title") or "Not"}” etiketleri: ' + (', '.join(n['tags']) or 'yok') + '.'
    return _not_degistir(a, ne)


def sabitle(a: dict) -> str:
    acik = a.get('acik')
    acik = True if acik is None else (acik if isinstance(acik, bool) else str(acik).lower() not in ('false', '0', 'hayır', 'hayir'))

    def ne(n, items, board):
        n['pinned'] = acik
        return f'“{n.get("title") or "Not"}” ' + ('sabitlendi.' if acik else 'sabitlemesi kaldırıldı.')
    return _not_degistir(a, ne)


def baglan(a: dict) -> str:
    hedef = _s(a, 'hedef', 'yeni_baslik')
    if not hedef:
        return 'Hangi notla bağlayayım? (hedef: ikinci notun başlığı).'
    sonuc = []

    def fn(items):
        board = F._board(items)
        gizli = F._gizli_idler(items)
        n1 = F._not_eslestir(board['notes'], gizli, _s(a, 'baslik', 'metin'))
        n2 = F._not_eslestir(board['notes'], gizli, hedef)
        if n1 is None or n2 is None:
            sonuc.append(('yok', 'ilk' if n1 is None else 'ikinci'))
            return
        if n1.get('id') == n2.get('id'):
            sonuc.append(('ayni',))
            return
        links = board.setdefault('links', [])
        if any(isinstance(l, dict) and {l.get('from'), l.get('to')} == {n1['id'], n2['id']} for l in links):
            sonuc.append(('var', n1.get('title'), n2.get('title')))
            return
        links.append({'id': F._yeni_id(), 'from': n1['id'], 'to': n2['id']})
        items[F.KEY_BOARD] = json.dumps(board, ensure_ascii=False)
        sonuc.append(('ok', n1.get('title'), n2.get('title')))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', 'ilk')
    if d[0] == 'ok':
        return f'“{d[1]}” ile “{d[2]}” bağlandı (panoda çizgi olarak görünür).'
    if d[0] == 'var':
        return 'Bu iki not zaten bağlı.'
    if d[0] == 'ayni':
        return 'Bir notu kendisiyle bağlayamam.'
    return f'{d[1]} notu bulunamadı.'


def _kelime_seti(n: dict) -> set:
    return F._kelimeler(str(n.get('title') or '') + ' ' + str(n.get('text') or '')[:1500]) | {('#' + F._fold(t)) for t in (n.get('tags') or [])}


def benzer(a: dict) -> str:
    items = F.snapshot_oku()['items']
    n, adaylar = _not_bul(items, _s(a, 'baslik', 'metin'))
    if n is None:
        return _bulunamadi(_s(a, 'baslik', 'metin'), adaylar)
    kn = _kelime_seti(n)
    skorlar = []
    for q in _gorunur_notlar(items):
        if q.get('id') == n.get('id') or re.search(r'\(devam \d+\)\s*$', str(q.get('title') or '')):
            continue
        kq = _kelime_seti(q)
        ortak = kn & kq
        if len(ortak) >= 2:
            skorlar.append((len(ortak) / max(1, min(len(kn), len(kq))), len(ortak), q, sorted(x for x in ortak if not x.startswith('#'))[:5] + sorted(x for x in ortak if x.startswith('#'))))
    skorlar.sort(key=lambda x: (-x[0], -x[1]))
    if not skorlar:
        return f'“{n.get("title")}” ile belirgin ortak sözcüğü olan başka not bulamadım.'
    return f'“{n.get("title")}” ile ilişkili notlar:\n' + '\n'.join(f'- {q.get("title") or _kisa(q.get("text"), 40)} (ortak: {", ".join(o)})' for _, _, q, o in skorlar[:6]) + \
           '\n(Bağlamak için baglan işlemi.)'


GELISTIR_TALIMAT = ('Sen deneyimli bir ürün/proje danışmanısın. Kullanıcının Fikir Alanım notunu geliştir. Türkçe, SOMUT ve kısa yaz (en çok 450 kelime), düz metin '
                    '(Markdown işareti yok, maddeler "- " ile). Başlıklar BÜYÜK HARFLE: NET TANIM (1-2 cümle) · KİME/NEYE FAYDA · İLK 3 ADIM (bugün yapılabilecek kadar küçük) · '
                    'RİSKLER VE BİLİNMEYENLER · ÖLÇÜT (nasıl anlarız) · SORULACAK SORULAR (2-3). Notta olmayan olguyu uydurma; varsayımsa "varsayım" de. {yon}')


BEKLE_SN = 20      # uygulamanın araç zaman sınırı 30 sn; daha uzun süren geliştirme arka planda biter ve duyurulur


def _gelistir_yap(baslik: str, metin_: str, yon: str) -> str:
    ek = _ek()
    girdi = f'NOT BAŞLIĞI: {baslik}\nNOT METNİ:\n{metin_[:6000]}'
    try:
        metin = ek._uret_metin(GELISTIR_TALIMAT.format(yon=(f'Özellikle şu yöne odaklan: {yon}.' if yon else '')), girdi, json=False, max_token=1800, zaman_ms=45000, sicaklik=0.5)
    except Exception as exc:
        log('ek_fikir_arac: fikir geliştirme başarısız', type(exc).__name__, str(exc)[:100])
        return 'Fikri şu an geliştiremedim (model yanıt vermedi). Biraz sonra yeniden dene.'
    metin = ek._duz_metin(metin)
    if len(metin) < 80:
        return 'Model anlamlı bir geliştirme üretemedi; yeniden dene.'
    r = F.not_yaz(baslik, 'FİKİR GELİŞTİRME' + (f' ({yon})' if yon else '') + '\n' + metin, ekle=True)
    return (f'“{r.get("eklenen") or r["baslik"]}” notunun sonuna geliştirme eklendi ({len(metin)} karakter). ÖZET: {_kisa(metin, 500)}\n'
            'Kullanıcıya ilk 3 adımı ve en büyük riski kısaca söyle; notun tamamını okuma.')


def fikir_gelistir(a: dict) -> str:
    import threading
    items = F.snapshot_oku()['items']
    n, adaylar = _not_bul(items, _s(a, 'baslik', 'metin'))
    if n is None:
        return _bulunamadi(_s(a, 'baslik', 'metin'), adaylar)
    baslik, metin_, yon = str(n.get('title') or ''), str(n.get('text') or ''), _s(a, 'yon')
    sonuc = []
    bitti = threading.Event()
    gec = {'evet': False}

    def is_():
        s_ = _gelistir_yap(baslik, metin_, yon)
        sonuc.append(s_)
        bitti.set()
        if gec['evet']:
            from . import ek_isler
            ek_isler.teslim_et('gelistir', f'[FİKİR GELİŞTİRME BİTTİ] “{baslik}”: ' + s_)
    threading.Thread(target=is_, daemon=True, name='fikir-gelistir').start()
    if bitti.wait(BEKLE_SN):
        return sonuc[0]
    gec['evet'] = True
    if bitti.is_set() and sonuc:      # tam sınırda bitti: duyuru yarışı olmasın
        return sonuc[0]
    return f'“{baslik}” için geliştirme sürüyor (model yavaş). Bitince notun sonuna yazılacak ve sana haber vereceğim; şimdilik başka işe geçebilirsin.'


def _eylem_satirlari(metin: str) -> list[str]:
    out = []
    for ln in str(metin or '').splitlines():
        m = re.match(r'^\s*(?:[-*•]\s*(?:\[[ xX]?\]\s*)?|\d+[.)]\s+|\[[ ]?\]\s*)(.{4,160})$', ln)
        if m and not re.search(r'(?i)^(özet|sonuç|kaynak)', m[1].strip()):
            out.append(' '.join(m[1].split()))
    return out


def fikri_goreve_cevir(a: dict) -> str:
    items = F.snapshot_oku()['items']
    n, adaylar = _not_bul(items, _s(a, 'baslik', 'metin'))
    if n is None:
        return _bulunamadi(_s(a, 'baslik', 'metin'), adaylar)
    satirlar = _eylem_satirlari(str(n.get('text') or ''))
    # "FİKİR GELİŞTİRME" bölümündeki "İLK 3 ADIM" varsa yalnızca onları al
    mm = re.search(r'İLK 3 ADIM\s*\n((?:\s*[-*•\d].*\n?)+)', str(n.get('text') or ''))
    if mm:
        ilk = _eylem_satirlari(mm.group(1))
        satirlar = ilk or satirlar
    if not satirlar:
        satirlar = [f'{n.get("title") or "Fikir"}: ilk adımı belirle']
    satirlar = satirlar[:10]
    gun, oncelik, kat = a.get('gun'), _s(a, 'oncelik') or 'normal', _s(a, 'kategori') or None
    yeni = []
    for s_ in satirlar:
        r = F.gorev_ekle(s_, gun, None, oncelik, kat)
        yeni.append(('zaten vardı: ' if r['var'] else '') + r['metin'])
    return f'“{n.get("title")}” notundan {len(yeni)} görev ({F.gun_coz(gun, F.bugun()).isoformat()}):\n' + '\n'.join(f'- {x}' for x in yeni)


# --------------------------------------------------------------------------- GÖREVLER
def gorev_toplu(a: dict) -> str:
    ham = str(a.get('metin') or a.get('maddeler') or '')
    satirlar = [re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', '', x).strip() for x in re.split(r'[\n;]+', ham)]
    satirlar = [x for x in satirlar if x][:30]
    if not satirlar:
        return 'Eklenecek görev listesi boş (metin: satır ya da ; ile ayrılmış görevler).'
    ort_saat = F.saat_coz(a.get('saat')) if a.get('saat') else None
    eklenen, var = [], []
    for s_ in satirlar:
        try:
            r = F.gorev_ekle(s_, a.get('gun'), ort_saat if not F.metinden_saat(s_)[0] else None, _s(a, 'oncelik') or 'normal', _s(a, 'kategori') or None)
        except ValueError:
            continue
        (var if r['var'] else eklenen).append(f'{(r["saat"] + " ") if r["saat"] else ""}{r["metin"]}')
    gun = F.gun_coz(a.get('gun'), F.bugun()).isoformat()
    out = f'{len(eklenen)} görev eklendi ({gun}):\n' + '\n'.join(f'- {x}' for x in eklenen) if eklenen else 'Yeni görev eklenmedi.'
    if var:
        out += '\nZaten vardı: ' + '; '.join(var)
    return out


def _geciken_liste(items: dict) -> list[dict]:
    bu = F.bugun()
    gs = [g for g in F.gorevler(items) if not g['bitti'] and (F.gun_coz(g['gun'], bu) or bu) < bu]
    gs.sort(key=lambda g: (g['gun'], g['saat'] or '99:99'))
    return gs


def geciken(a: dict) -> str:
    items = F.snapshot_oku()['items']
    gs = _geciken_liste(items)
    if not gs:
        return 'Geciken açık görev yok.'
    bu = F.bugun()
    return f'{len(gs)} geciken görev:\n' + '\n'.join(f'- {g["metin"]} ({(bu - F.gun_coz(g["gun"], bu)).days} gün gecikmiş, {g["gun"]})' + ({'high': ' ❗', 'important': ' ⭑'}.get(g['oncelik'], '')) for g in gs[:40]) + \
           '\n(Hepsini bugüne almak için geciken_tasi; tek tek ertelemek için gorev_duzenle.)'


def geciken_tasi(a: dict) -> str:
    hedef = F.gun_coz(a.get('gun'), F.bugun())
    sayi = []

    def fn(items):
        raw = F._json_oku(items, F.KEY_TASKS, [])
        raw = raw if isinstance(raw, list) else []
        gizli = F._gizli_idler(items)
        bu = F.bugun()
        for t in raw:
            if not isinstance(t, dict) or t.get('done') or (t.get('cat') in gizli and t.get('cat') is not None):
                continue
            d = F.gun_coz(str(t.get('day') or ''), bu)
            if d and d < bu:
                t['day'] = hedef.isoformat()
                t['carried'] = True
                sayi.append(1)
        items[F.KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
    F.duzenle(fn)
    return f'{len(sayi)} geciken görev {hedef.isoformat()} gününe taşındı.' if sayi else 'Taşınacak geciken görev yok.'


def gorev_kategori(a: dict) -> str:
    anahtar, kat = _s(a, 'metin'), _s(a, 'kategori')
    if not anahtar or not kat:
        return 'Hangi görev ve hangi kategori? (metin + kategori).'
    sonuc = []

    def fn(items):
        kid = _kat_id(items, kat)
        if kid is None:
            sonuc.append(('kat',))
            return
        raw, idx = F._eslestir(items, anahtar)
        if len(idx) != 1:
            sonuc.append(('coklu' if idx else 'yok',))
            return
        raw[idx[0]]['cat'] = kid
        items[F.KEY_TASKS] = json.dumps(raw, ensure_ascii=False)
        sonuc.append(('ok', F.metinden_saat(str(raw[idx[0]].get('text', '')))[1]))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok',)
    if d[0] == 'ok':
        return f'“{d[1]}” görevi “{kat}” kategorisine alındı.'
    if d[0] == 'kat':
        return f'“{kat}” adlı kategori yok (kategoriler / kategori_ekle).'
    return 'Birden çok göreve uyuyor; daha açık söyle.' if d[0] == 'coklu' else 'Böyle açık bir görev yok.'


# --------------------------------------------------------------------------- HAFTA / PLAN
def _dk(saat: str) -> int:
    h, m = saat.split(':')
    return int(h) * 60 + int(m)


def _hhmm(dk: int) -> str:
    return f'{dk // 60:02d}:{dk % 60:02d}'


def _gun_dilimleri(d: dt.date) -> list[tuple[int, int, str]]:
    """O günün meşgul aralıkları (dk): haftalık program blokları + saatli açık görevler (30 dk varsayım)."""
    out = []
    for e in F.hafta_etkinlikleri(dt.datetime.combine(d, dt.time(0, 0)), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0, 0))):
        b = dt.datetime.fromtimestamp(e['start_ts'])
        s_ = b.hour * 60 + b.minute
        out.append((s_, min(1440, s_ + max(15, (e['end_ts'] - e['start_ts']) // 60)), e['title']))
    for g in F.gorevler():
        if not g['bitti'] and g['saat'] and F.gun_coz(g['gun'], F.bugun()) == d:
            s_ = _dk(g['saat'])
            out.append((s_, min(1440, s_ + 30), g['metin']))
    out.sort()
    return out


def _bos_aralik(d: dt.date, bas: int, bit: int, min_dk: int) -> list[tuple[int, int]]:
    if d == F.bugun():
        simdi = dt.datetime.now()
        bas = max(bas, ((simdi.hour * 60 + simdi.minute + 14) // 15) * 15)
    bos, imlec = [], bas
    for s_, e_, _ in _gun_dilimleri(d):
        if e_ <= imlec:
            continue
        if s_ > imlec and min(s_, bit) - imlec >= min_dk:
            bos.append((imlec, min(s_, bit)))
        imlec = max(imlec, e_)
        if imlec >= bit:
            break
    if bit - imlec >= min_dk:
        bos.append((imlec, bit))
    return bos


def _calisma_saatleri(a: dict) -> tuple[int, int]:
    bas = F.saat_coz(a.get('baslangic')) or CALISMA[0]
    bit = F.saat_coz(a.get('bitis')) or CALISMA[1]
    b, e = _dk(bas), _dk(bit)
    return (b, e) if e > b else (_dk(CALISMA[0]), _dk(CALISMA[1]))


def bos_zaman(a: dict) -> str:
    d = F.gun_coz(a.get('gun'), F.bugun())
    bas, bit = _calisma_saatleri(a)
    min_dk = max(15, int(a.get('sure_dk') or 30))
    bos = _bos_aralik(d, bas, bit, min_dk)
    ad = f'{F.TR_GUN[d.weekday()]} {d.day}.{d.month:02d}'
    if not bos:
        return f'{ad}: {_hhmm(bas)}–{_hhmm(bit)} arasında {min_dk} dk’lık boş aralık yok.'
    toplam = sum(e - s for s, e in bos)
    return f'{ad} boş aralıklar ({_hhmm(bas)}–{_hhmm(bit)}, en az {min_dk} dk), toplam {toplam // 60} sa {toplam % 60} dk:\n' + '\n'.join(f'- {_hhmm(s)}–{_hhmm(e)} ({e - s} dk)' for s, e in bos)


def _sure_cikar(metin: str) -> int:
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(dk|dakika|saat|sa)\b', F._fold(metin))
    if not m:
        return VARSAYILAN_DK
    v = float(m[1].replace(',', '.'))
    return max(15, min(240, int(round(v * (60 if m[2] in ('saat', 'sa') else 1) / 15) * 15)))


def _plan_hesapla(d: dt.date, a: dict):
    bas, bit = _calisma_saatleri(a)
    bu = F.bugun()
    aday = []
    for g in F.gorevler():
        if g['bitti'] or g['saat']:
            continue
        gd = F.gun_coz(g['gun'], bu)
        if gd == d or (d == bu and gd < bu):
            aday.append(g)
    aday.sort(key=lambda g: (ONCELIK_SIRA.get(g['oncelik'], 2), g['gun'], g['metin']))
    bos = _bos_aralik(d, bas, bit, 15)
    plan, sigmayan = [], []
    for g in aday:
        sure = _sure_cikar(g['metin'])
        yer = False
        for i, (s_, e_) in enumerate(bos):
            if e_ - s_ >= sure:
                plan.append((s_, s_ + sure, g))
                bos[i] = (s_ + sure + ARA_DK, e_) if s_ + sure + ARA_DK < e_ else (e_, e_)
                yer = True
                break
        if not yer:
            sigmayan.append(g)
    plan.sort(key=lambda x: x[0])
    return plan, sigmayan


def planla(a: dict) -> str:
    d = F.gun_coz(a.get('gun'), F.bugun())
    plan, sigmayan = _plan_hesapla(d, a)
    ad = f'{F.TR_GUN[d.weekday()]} {d.day}.{d.month:02d}'
    mevcut = _gun_dilimleri(d)
    satir = [f'{ad} için ÖNERİLEN PLAN (öncelik sırasına göre, mevcut program ve saatli görevler korunarak; görev başına {VARSAYILAN_DK} dk varsayım, "(30 dk)" gibi yazıldıysa o):']
    for s_, e_, g in plan:
        satir.append(f'- {_hhmm(s_)}–{_hhmm(e_)} {g["metin"]}' + ({'high': ' ❗', 'important': ' ⭑'}.get(g['oncelik'], '')) + (f' (gecikmiş: {g["gun"]})' if g['gun'] != d.isoformat() else ''))
    if not plan:
        satir.append('- (yerleştirilecek saatsiz açık görev yok)')
    if sigmayan:
        satir.append('Sığmayan (başka güne ertele ya da süreyi kıs): ' + '; '.join(g['metin'] for g in sigmayan[:10]))
    if mevcut:
        satir.append('Zaten dolu: ' + '; '.join(f'{_hhmm(s_)}–{_hhmm(e_)} {t}' for s_, e_, t in mevcut[:8]))
    satir.append('Kullanıcıya planı kısaca oku; onaylarsa plan_uygula ile haftalık programa blok olarak yaz.')
    return '\n'.join(satir)


def plan_uygula(a: dict) -> str:
    d = F.gun_coz(a.get('gun'), F.bugun())
    plan, _ = _plan_hesapla(d, a)
    if not plan:
        return 'Yazılacak plan yok.'
    for s_, e_, g in plan:
        F.hafta_ekle(g['metin'], d, _hhmm(s_), e_ - s_, False, 'focus', 'Plan: Fikir görevinden')
    return f'{len(plan)} blok {d.isoformat()} günü haftalık programa yazıldı: ' + '; '.join(f'{_hhmm(s_)} {g["metin"]}' for s_, _, g in plan)


def _blok_adi(b: dict) -> str:
    gun = F.TR_GUN[int(b.get('day', 0)) % 7]
    s_ = int(b.get('start', 0))
    return f'{gun} {_hhmm(s_)}–{_hhmm(s_ + int(b.get("dur", 60)))} {b.get("title", "")}' + ('' if b.get('once') else ' (her hafta)')


def hafta_oku(a: dict) -> str:
    items = F.snapshot_oku()['items']
    bloklar = F.hafta_bloklari(items)
    if not bloklar:
        return 'Haftalık programda blok yok.'
    bu = F.bugun()
    pzt = F._pazartesi(F.gun_coz(a.get('gun'), bu) or bu).isoformat()
    gorunen = [b for b in bloklar if (not b.get('once')) or b.get('week') == pzt]
    istek = F._fold(str(a.get('gun') or ''))
    d = F.gun_coz(a.get('gun'), None) if istek and istek not in ('hafta', 'bu hafta', 'haftalik', 'tum hafta') else None
    if d is not None:
        gorunen = [b for b in gorunen if int(b.get('day', -1)) == d.weekday()]
    gorunen.sort(key=lambda b: (int(b.get('day', 0)), int(b.get('start', 0))))
    return f'{len(gorunen)} blok:\n' + '\n'.join('- ' + _blok_adi(b) for b in gorunen) if gorunen else 'Bu hafta/gün için blok yok.'


def _blok_bul(items: dict, ad: str, gun):
    f = F._fold(ad)
    hit = [b for b in F.hafta_bloklari(items) if f and (f == F._fold(b.get('title', '')) or f in F._fold(b.get('title', '')))]
    if gun and len(hit) > 1:
        d = F.gun_coz(gun, None)
        if d is not None:
            alt = [b for b in hit if int(b.get('day', -1)) == d.weekday()]
            hit = alt or hit
    exact = [b for b in hit if F._fold(b.get('title', '')) == f]
    return exact or hit


def hafta_duzenle(a: dict) -> str:
    ad = _s(a, 'baslik', 'metin')
    sonuc = []

    def fn(items):
        hit = _blok_bul(items, ad, a.get('gun') if not a.get('yeni_gun') else None)
        if len(hit) != 1:
            sonuc.append(('coklu' if hit else 'yok', [_blok_adi(b) for b in hit[:5]]))
            return
        b = hit[0]
        w = F._json_oku(items, F.KEY_WEEK, {})
        for blk in w['blocks']:
            if blk.get('id') == b.get('id'):
                if a.get('yeni_baslik'):
                    blk['title'] = str(a['yeni_baslik'])[:80]
                yg = a.get('yeni_gun')
                if yg:
                    d = F.gun_coz(yg, None)
                    if d is None:
                        sonuc.append(('gun',))
                        return
                    blk['day'] = d.weekday()
                    if blk.get('once'):
                        blk['week'] = F._pazartesi(d).isoformat()
                if a.get('baslangic'):
                    sa = F.saat_coz(a['baslangic'])
                    if not sa:
                        sonuc.append(('saat',))
                        return
                    blk['start'] = min(1439, round(_dk(sa) / 15) * 15)
                if a.get('sure_dk'):
                    blk['dur'] = max(15, min(720, round(int(a['sure_dk']) / 15) * 15))
                if a.get('renk') in F.RENKLER:
                    blk['color'] = a['renk']
                sonuc.append(('ok', _blok_adi(blk)))
        items[F.KEY_WEEK] = json.dumps(w, ensure_ascii=False)
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', [])
    if d[0] == 'ok':
        return 'Blok güncellendi: ' + d[1]
    if d[0] == 'coklu':
        return f'“{ad}” birden çok bloğa uyuyor: ' + '; '.join(d[1]) + '. Günü de söyle.'
    if d[0] in ('gun', 'saat'):
        return 'Yeni gün/saat anlaşılamadı (yeni_gun: cuma ya da 2026-11-06; baslangic: 14:30).'
    return f'“{ad}” adlı blok yok.'


def hafta_sil(a: dict) -> str:
    ad = _s(a, 'baslik', 'metin')
    sonuc = []

    def fn(items):
        hit = _blok_bul(items, ad, a.get('gun'))
        if len(hit) != 1:
            sonuc.append(('coklu' if hit else 'yok', [_blok_adi(b) for b in hit[:5]]))
            return
        w = F._json_oku(items, F.KEY_WEEK, {})
        w['blocks'] = [b for b in w['blocks'] if b.get('id') != hit[0].get('id')]
        items[F.KEY_WEEK] = json.dumps(w, ensure_ascii=False)
        sonuc.append(('ok', _blok_adi(hit[0])))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', [])
    if d[0] == 'ok':
        return 'Bloktan silindi: ' + d[1]
    return (f'“{ad}” birden çok bloğa uyuyor: ' + '; '.join(d[1]) + '. Günü de söyle.') if d[0] == 'coklu' else f'“{ad}” adlı blok yok.'


# --------------------------------------------------------------------------- RUTİNLER
def _rutinler(items: dict) -> list[dict]:
    r = F._json_oku(items, KEY_ROUTINE, [])
    return [x for x in r if isinstance(x, dict)] if isinstance(r, list) else []


def rutin_oku(a: dict) -> str:
    items = F.snapshot_oku()['items']
    rs = _rutinler(items)
    if not rs:
        return 'Rutin yok.'
    bu = _tarih_anahtari()
    satir = []
    for r in rs:
        dbd = r.get('doneByDate') if isinstance(r.get('doneByDate'), dict) else {}
        seri = 0
        d = F.bugun() if dbd.get(bu) else F.bugun() - dt.timedelta(days=1)
        while dbd.get(d.isoformat()):
            seri += 1
            d -= dt.timedelta(days=1)
        son7 = sum(1 for i in range(7) if dbd.get((F.bugun() - dt.timedelta(days=i)).isoformat()))
        satir.append(f'- {r.get("icon", "•")} {r.get("text", "")}: bugün {"✔ yapıldı" if dbd.get(bu) else "yapılmadı"}; son 7 günde {son7}/7; seri {seri} gün')
    return f'{len(rs)} rutin:\n' + '\n'.join(satir)


def rutin_ekle(a: dict) -> str:
    metin = ' '.join(_s(a, 'metin', 'baslik').split())[:80]
    if not metin:
        return 'Rutin metni boş.'
    ikon = _s(a, 'ikon') or '•'
    sonuc = []

    def fn(items):
        rs = F._json_oku(items, KEY_ROUTINE, [])
        rs = rs if isinstance(rs, list) else []
        if any(isinstance(r, dict) and F._fold(r.get('text', '')) == F._fold(metin) for r in rs):
            sonuc.append('var')
            return
        rs.append({'id': 'routine-' + uuid.uuid4().hex[:8], 'text': metin, 'icon': ikon[:2], 'doneByDate': {}})
        items[KEY_ROUTINE] = json.dumps(rs, ensure_ascii=False)
        sonuc.append('ok')
    F.duzenle(fn)
    return f'Rutin eklendi: {ikon[:2]} {metin}' if sonuc and sonuc[0] == 'ok' else 'Bu rutin zaten var.'


def _rutin_bul(items: dict, ad: str):
    f = F._fold(ad)
    rs = F._json_oku(items, KEY_ROUTINE, [])
    rs = rs if isinstance(rs, list) else []
    hit = [r for r in rs if isinstance(r, dict) and f and (f == F._fold(r.get('text', '')) or f in F._fold(r.get('text', '')))]
    exact = [r for r in hit if F._fold(r.get('text', '')) == f]
    return rs, exact or hit


def rutin_yap(a: dict) -> str:
    ad = _s(a, 'metin', 'baslik')
    yapildi = a.get('acik')
    yapildi = True if yapildi is None else (yapildi if isinstance(yapildi, bool) else str(yapildi).lower() not in ('false', '0', 'hayır', 'hayir'))
    gun = F.gun_coz(a.get('gun'), F.bugun()).isoformat()
    sonuc = []

    def fn(items):
        rs, hit = _rutin_bul(items, ad)
        if len(hit) != 1:
            sonuc.append(('coklu' if hit else 'yok', [r.get('text') for r in hit[:5]]))
            return
        dbd = hit[0].setdefault('doneByDate', {})
        if yapildi:
            dbd[gun] = True
        else:
            dbd.pop(gun, None)
        items[KEY_ROUTINE] = json.dumps(rs, ensure_ascii=False)
        sonuc.append(('ok', hit[0].get('text')))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok', [])
    if d[0] == 'ok':
        return f'“{d[1]}” {gun} için ' + ('yapıldı olarak işaretlendi.' if yapildi else 'yapılmadı olarak geri alındı.')
    return ('Birden çok rutine uyuyor: ' + '; '.join(d[1])) if d[0] == 'coklu' else f'“{ad}” adlı rutin yok.'


def rutin_sil(a: dict) -> str:
    ad = _s(a, 'metin', 'baslik')
    sonuc = []

    def fn(items):
        rs, hit = _rutin_bul(items, ad)
        if len(hit) != 1:
            sonuc.append(('coklu' if hit else 'yok',))
            return
        _cop_kutusu(items, 'routine', hit[0].get('text') or 'Rutin', {'routine': hit[0]})
        items[KEY_ROUTINE] = json.dumps([r for r in rs if r.get('id') != hit[0].get('id')], ensure_ascii=False)
        sonuc.append(('ok', hit[0].get('text')))
    F.duzenle(fn)
    d = sonuc[0] if sonuc else ('yok',)
    return f'“{d[1]}” rutini silindi (geri dönüşüm kutusunda).' if d[0] == 'ok' else ('Birden çok rutine uyuyor; daha açık söyle.' if d[0] == 'coklu' else f'“{ad}” adlı rutin yok.')


# --------------------------------------------------------------------------- GÜNLÜK
def gunluk_oku(a: dict) -> str:
    items = F.snapshot_oku()['items']
    j = F._json_oku(items, KEY_JOURNAL, {})
    j = j if isinstance(j, dict) else {}
    d = F.gun_coz(a.get('gun'), F.bugun()).isoformat()
    e = j.get(d)
    if isinstance(e, str):
        e = {'title': '', 'text': e}
    if not e or not str(e.get('text') or '').strip():
        son = sorted(k for k, v in j.items() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', k) and v)[-5:]
        return f'{d} için günlük yazısı yok.' + (f' Son yazılar: {", ".join(son)}.' if son else '')
    t = str(e.get('text') or '')
    return f'Günlük {d}' + (f' — {e.get("title")}' if e.get('title') else '') + f' ({len(t)} karakter):\n' + t[:5000]


def gunluk_yaz(a: dict) -> str:
    metin = str(a.get('metin') or '').strip()
    if not metin:
        return 'Günlüğe yazılacak metin boş.'
    d = F.gun_coz(a.get('gun'), F.bugun()).isoformat()
    sonuc = []

    def fn(items):
        j = F._json_oku(items, KEY_JOURNAL, {})
        j = j if isinstance(j, dict) else {}
        e = j.get(d)
        e = {'title': '', 'text': e} if isinstance(e, str) else (dict(e) if isinstance(e, dict) else {'title': '', 'text': ''})
        mevcut = str(e.get('text') or '')
        ek_ = (f'\n\n— {time.strftime("%H:%M")} —\n' if mevcut.strip() else '') + metin
        if len(mevcut) + len(ek_) > 20000:
            sonuc.append(('uzun',))
            return
        e['text'] = (mevcut + ek_)
        if a.get('baslik') and not e.get('title'):
            e['title'] = str(a['baslik'])[:120]
        e['updatedAt'] = dt.datetime.utcnow().isoformat() + 'Z'
        j[d] = e
        items[KEY_JOURNAL] = json.dumps(j, ensure_ascii=False)
        sonuc.append(('ok', len(e['text'])))
    F.duzenle(fn)
    d_ = sonuc[0] if sonuc else ('uzun',)
    return f'Günlüğe ({d}) eklendi; toplam {d_[1]} karakter.' if d_[0] == 'ok' else 'Günlük 20.000 karakter sınırına dayandı; kısa bir özetle yeni gün aç.'


# --------------------------------------------------------------------------- KAYNAKLAR
def kaynak_ekle(a: dict) -> str:
    url = _s(a, 'url')
    metin = str(a.get('metin') or '').strip()
    baslik = ' '.join(_s(a, 'baslik').split())[:120]
    if url and not re.match(r'^https?://\S+$', url):
        return 'Adres http:// ya da https:// ile başlamalı.'
    if not url and not metin:
        return 'Kaynak için adres (url) ya da metin ver.'
    if not baslik:
        baslik = (re.sub(r'^https?://(www\.)?', '', url).split('/')[0] if url else ' '.join(metin.split()[:6]))
    sonuc = []

    def fn(items):
        rs = F._json_oku(items, KEY_RESOURCES, [])
        rs = rs if isinstance(rs, list) else []
        if url and any(isinstance(r, dict) and r.get('url') == url for r in rs):
            sonuc.append('var')
            return
        simdi = dt.datetime.utcnow().isoformat() + 'Z'
        rs.insert(0, {'id': 'res-' + uuid.uuid4().hex[:8], 'type': 'link' if url else 'note', 'url': url, 'title': baslik, 'categoryId': _kat_id(items, _s(a, 'kategori')),
                      'text': metin[:8000], 'tags': [t.lstrip('#') for t in _liste_metni(a.get('etiketler'))][:16], 'color': '#eef2ed', 'pinned': False,
                      'createdAt': simdi, 'updatedAt': simdi})
        items[KEY_RESOURCES] = json.dumps(rs, ensure_ascii=False)
        sonuc.append('ok')
    F.duzenle(fn)
    return f'Kaynaklara eklendi: {baslik}' if sonuc and sonuc[0] == 'ok' else 'Bu adres kaynaklarda zaten var.'


def kaynak_ara(a: dict) -> str:
    items = F.snapshot_oku()['items']
    gizli = F._gizli_idler(items)
    rs = [r for r in (F._json_oku(items, KEY_RESOURCES, []) or []) if isinstance(r, dict) and not (r.get('categoryId') in gizli and r.get('categoryId') is not None)]
    toks = [t for t in F._fold(_s(a, 'sorgu', 'metin', 'baslik')).split() if len(t) >= 2]
    sat = []
    for r in rs:
        f = F._fold(f'{r.get("title", "")} {r.get("text", "")} {r.get("url", "")} {" ".join(r.get("tags") or [])}')
        if all(t in f for t in toks):
            sat.append(f'- {r.get("title") or r.get("url")}' + (f' — {r.get("url")}' if r.get('url') else '') + (f' #{" #".join(r.get("tags") or [])}' if r.get('tags') else ''))
    if not rs:
        return 'Kaynaklar bölümü boş.'
    return (f'{len(sat)} kaynak:\n' + '\n'.join(sat[:25])) if sat else 'Buna uyan kaynak yok.'


# --------------------------------------------------------------------------- KATEGORİLER
def kategoriler(a: dict) -> str:
    items = F.snapshot_oku()['items']
    gizli = F._gizli_idler(items)
    cats = [c for c in (F._json_oku(items, F.KEY_CATS, []) or []) if isinstance(c, dict) and c.get('id') not in gizli]
    if not cats:
        return 'Kategori yok.'
    gs, ns = F.gorevler(items), _gorunur_notlar(items)
    return 'Kategoriler:\n' + '\n'.join(f'- {c.get("name")}: {sum(1 for g in gs if g["kat"] == c.get("name") and not g["bitti"])} açık görev, {sum(1 for n in ns if n.get("categoryId") == c.get("id"))} not' for c in cats)


def kategori_ekle(a: dict) -> str:
    ad = ' '.join(_s(a, 'baslik', 'metin', 'kategori').split())[:24]
    if not ad:
        return 'Kategori adı boş.'
    if F._fold(ad) == 'gizli':
        return '“Gizli” kategorisi özeldir; yapay zekâya görünmeyen alan olarak yalnızca sen yönetirsin.'
    sonuc = []
    renkler = ['#8c2b2b', '#a65338', '#b58445', '#7a7a3f', '#3f7a5a', '#3f6f7a', '#4a5a8c', '#6a4a8c']

    def fn(items):
        cats = F._json_oku(items, F.KEY_CATS, [])
        cats = cats if isinstance(cats, list) else []
        if any(isinstance(c, dict) and F._fold(c.get('name', '')) == F._fold(ad) for c in cats):
            sonuc.append('var')
            return
        cats.append({'id': 'cat-' + uuid.uuid4().hex[:8], 'name': ad, 'color': renkler[len(cats) % len(renkler)], 'aiHidden': False})
        items[F.KEY_CATS] = json.dumps(cats, ensure_ascii=False)
        sonuc.append('ok')
    F.duzenle(fn)
    return f'“{ad}” kategorisi eklendi.' if sonuc and sonuc[0] == 'ok' else 'Bu kategori zaten var.'


# --------------------------------------------------------------------------- GÖZDEN GEÇİR
def gozden_gecir(a: dict) -> str:
    items = F.snapshot_oku()['items']
    bu = F.bugun()
    k = F._fold(_s(a, 'kapsam') or 'hafta')
    gun_sayisi = 1 if k in ('bugun', 'gun', 'today') else 7
    baslangic = bu - dt.timedelta(days=gun_sayisi - 1)
    gs = F.gorevler(items)

    def gunu(g, anahtar):
        return F.gun_coz(str(g['ham'].get(anahtar) or ''), None)
    biten = [g for g in gs if g['bitti'] and (gunu(g, 'doneDay') or gunu(g, 'day')) and baslangic <= (gunu(g, 'doneDay') or gunu(g, 'day')) <= bu]
    acik = [g for g in gs if not g['bitti']]
    geciken_ = [g for g in acik if (F.gun_coz(g['gun'], bu) or bu) < bu]
    bugun_acik = [g for g in acik if F.gun_coz(g['gun'], bu) == bu]
    tasinan = [g for g in acik if g['ham'].get('carried')]
    satir = [f'{"BUGÜN" if gun_sayisi == 1 else "SON 7 GÜN"} GÖZDEN GEÇİRME ({baslangic.day}.{baslangic.month:02d}–{bu.day}.{bu.month:02d}):']
    satir.append(f'- Biten görev: {len(biten)}' + (' → ' + '; '.join(g['metin'] for g in biten[:8]) + ('…' if len(biten) > 8 else '') if biten else ''))
    satir.append(f'- Açık: {len(acik)} (bugün {len(bugun_acik)}, geciken {len(geciken_)}, ertelenip taşınan {len(tasinan)})')
    if geciken_:
        satir.append('- En eski gecikenler: ' + '; '.join(f'{g["metin"]} ({g["gun"]})' for g in geciken_[:5]))
    yuksek = [g for g in acik if g['oncelik'] == 'high']
    if yuksek:
        satir.append('- Yüksek öncelikli açık: ' + '; '.join(g['metin'] for g in yuksek[:5]))
    rs = _rutinler(items)
    if rs:
        parca = []
        for r in rs:
            dbd = r.get('doneByDate') if isinstance(r.get('doneByDate'), dict) else {}
            parca.append(f'{r.get("text")}: {sum(1 for i in range(gun_sayisi) if dbd.get((bu - dt.timedelta(days=i)).isoformat()))}/{gun_sayisi}')
        satir.append('- Rutinler: ' + '; '.join(parca))
    ns = [n for n in _gorunur_notlar(items) if not re.search(r'\(devam \d+\)\s*$', str(n.get('title') or ''))]
    kategorisiz = [n for n in ns if not n.get('categoryId')]
    satir.append(f'- Fikir panosu: {len(ns)} not, {len(kategorisiz)} tanesi kategorisiz' + (' → ' + '; '.join(str(n.get('title') or _kisa(n.get('text'), 30)) for n in kategorisiz[:5]) if kategorisiz else ''))
    j = F._json_oku(items, KEY_JOURNAL, {})
    if isinstance(j, dict):
        yazilan = sum(1 for i in range(gun_sayisi) if j.get((bu - dt.timedelta(days=i)).isoformat()))
        satir.append(f'- Günlük: {yazilan}/{gun_sayisi} gün yazılmış')
    satir.append('Kullanıcıya 4-5 cümlelik bir değerlendirme yap: iyi giden, takılan (geciken/ertelenen), ve TEK somut öneri (ör. geciken_tasi, planla, kategorisiz fikirleri düzenle).')
    return '\n'.join(satir)


def not_oku(a: dict) -> str:
    items = F.snapshot_oku()['items']
    ad = _s(a, 'baslik', 'metin')
    n, adaylar = _not_bul(items, ad)
    if n is None:
        return _bulunamadi(ad, adaylar)
    metin = str(n.get('text') or '')
    sayfa = max(1, int(a.get('sayfa') or 1))
    parca = metin[(sayfa - 1) * 6000: sayfa * 6000]
    toplam = max(1, -(-len(metin) // 6000))
    kat = F._kategori_adi(items, n.get('categoryId'))
    etk = ', '.join(n.get('tags') or [])
    ust = f'Not “{n.get("title")}” ({len(metin)} karakter' + (f', kategori {kat}' if kat else '') + (f', etiket {etk}' if etk else '') + (', sabit' if n.get('pinned') else '') + ')'
    if not parca:
        return ust + f': {sayfa}. sayfa yok (toplam {toplam}).'
    devam = [str(q.get('title')) for q in _gorunur_notlar(items) if str(q.get('title') or '').startswith(f'{n.get("title")} (devam')]
    return ust + (f' — sayfa {sayfa}/{toplam}' if toplam > 1 else '') + ':\n' + parca + (f'\n… (devamı için sayfa={sayfa + 1}; sesli okuma, kısaca anlat)' if sayfa < toplam else '') + \
        (f'\nDevam notları: {", ".join(devam)}' if devam and sayfa == 1 else '')


# --------------------------------------------------------------------------- ŞEMALAR (Fikirler panosunda diyagram)
def _sema_mod():
    from . import ek_sema
    return ek_sema


def _sema_kat(items: dict) -> str:
    """"Şemalar" kategorisinin id'si (yoksa açar)."""
    cats = F._json_oku(items, F.KEY_CATS, [])
    cats = cats if isinstance(cats, list) else []
    for c in cats:
        if isinstance(c, dict) and F._fold(c.get('name', '')) == F._fold(SEMA_KATEGORI):
            return c.get('id')
    cid = 'cat-' + uuid.uuid4().hex[:8]
    cats.append({'id': cid, 'name': SEMA_KATEGORI, 'color': '#3f6f7a', 'aiHidden': False})
    items[F.KEY_CATS] = json.dumps(cats, ensure_ascii=False)
    return cid


def _sema_tablo(items: dict) -> dict:
    t = F._json_oku(items, KEY_SEMA, {})
    return t if isinstance(t, dict) else {}


def _sema_uygula(n: dict, spec: dict, baslik: str) -> None:
    S = _sema_mod()
    n['images'] = [S.resim(spec, baslik)]
    n['text'] = S.ozet_metin(spec, baslik)[:F.NOT_MAX]
    n['size'] = 'medium'          # kart küçük kalsın; şema defterde metinle yan yana büyük görünür
    tags = [str(x) for x in (n.get('tags') or [])]
    for t in ('şema', S.TUR_AD.get(spec['tur'], spec['tur'])):
        if t not in tags:
            tags.append(t)
    n['tags'] = tags[:12]
    if baslik:
        n['title'] = baslik[:80]


def _sema_yer(board: dict, n: dict) -> None:
    """Şema kartı (orta boy) için; sayfa dünya birimini ~yarıya indirdiği için aralık geniş tutulur: diğer notların üstüne binmesin diye geniş boşluklu ilk yuvaya konur."""
    cam = board.get('camera') if isinstance(board.get('camera'), dict) else {}
    cx, cy = float(cam.get('x', 0) or 0), float(cam.get('y', 0) or 0)
    diger = [q for q in board['notes'] if isinstance(q, dict) and q is not n]
    for dy in (0, 420, -420, 840, -840):
        for dx in (0, 520, -520, 1040, -1040, 1560):
            x, y = cx + dx, cy + dy
            if not any(abs(float(q.get('x', 0)) - x) < 500 and abs(float(q.get('y', 0)) - y) < 400 for q in diger):
                n['x'], n['y'] = x, y
                return
    n['x'], n['y'] = max([float(q.get('x', 0)) for q in diger] or [0]) + 520, cy


def _sema_girdi(a: dict):
    return _s(a, 'dugumler', 'metin'), _s(a, 'baglantilar')


def sema_ekle(a: dict) -> str:
    S = _sema_mod()
    baslik = ' '.join(_s(a, 'baslik').split())[:80]
    if not baslik:
        return 'Şemaya bir başlık ver (ör. “Giriş akışı”).'
    dug, bag = _sema_girdi(a)
    spec = S.coz(_s(a, 'sema_turu', 'tur') or 'akis', dug, bag, _s(a, 'yon'))
    sonuc = []

    def fn(items):
        board = F._board(items)
        tablo = _sema_tablo(items)
        mevcut = None
        for q in board['notes']:
            if isinstance(q, dict) and str(q.get('title') or '') == baslik and 'şema' in [str(x) for x in (q.get('tags') or [])]:
                mevcut = q
        if mevcut is None:
            mevcut = F._yeni_not(board, baslik, '', ['şema'])
            _sema_yer(board, mevcut)
            sonuc.append('yeni')
        else:
            sonuc.append('yenilendi')
        mevcut['categoryId'] = _sema_kat(items)
        _sema_uygula(mevcut, spec, baslik)
        tablo[str(mevcut['id'])] = {'spec': spec, 'baslik': baslik}
        var = {str(q.get('id')) for q in board['notes'] if isinstance(q, dict)}
        for k in [k for k in tablo if k not in var]:
            tablo.pop(k)
        items[KEY_SEMA] = json.dumps(tablo, ensure_ascii=False)
        items[F.KEY_BOARD] = json.dumps(board, ensure_ascii=False)
    F.duzenle(fn)
    ad = S.TUR_AD.get(spec['tur'], spec['tur'])
    return (f'“{baslik}” {ad} Fikir Alanım › Fikirler panosuna ' + ('eklendi' if sonuc[0] == 'yeni' else 'yenilendi (aynı adlı şema güncellendi)') +
            f' ({len(spec["nodes"])} öğe, {len(spec["edges"])} bağlantı; “Şemalar” kategorisi). Kartı açıp resme dokunarak tam ekran görebilirsin; sonradan öğe eklemek/çıkarmak için sema_guncelle.')


def sema_guncelle(a: dict) -> str:
    S = _sema_mod()
    ad = _s(a, 'baslik')
    ek_d, ek_b = _sema_girdi(a)
    cikar = _liste_metni(a.get('cikar_dugum'))
    yeni_baslik = ' '.join(_s(a, 'yeni_baslik').split())[:80]
    yon = _s(a, 'yon')
    if not (ek_d or ek_b or cikar or yeni_baslik or yon):
        return 'Neyi değiştireyim? dugumler (eklenecek), baglantilar (eklenecek), cikar_dugum (silinecek), yon ya da yeni_baslik ver.'
    sonuc = []

    def fn(items):
        n, adaylar = _not_bul(items, ad)
        if n is None:
            sonuc.append(_bulunamadi(ad, adaylar))
            return
        kayit = _sema_tablo(items).get(str(n.get('id')))
        if not isinstance(kayit, dict) or not isinstance(kayit.get('spec'), dict):
            sonuc.append(f'“{n.get("title")}” BLOOM’un çizdiği bir şema değil ya da kaynağı kayıp; sema_ekle ile aynı başlıkla yeniden çiz.')
            return
        try:
            spec = S.guncelle(kayit['spec'], ek_d, ek_b, cikar, yon)
        except ValueError as exc:
            sonuc.append(str(exc))
            return
        baslik = yeni_baslik or str(n.get('title') or kayit.get('baslik') or '')
        board = F._board(items)
        for q in board['notes']:
            if isinstance(q, dict) and str(q.get('id')) == str(n.get('id')):
                _sema_uygula(q, spec, baslik)
        tablo = _sema_tablo(items)
        tablo[str(n.get('id'))] = {'spec': spec, 'baslik': baslik}
        items[KEY_SEMA] = json.dumps(tablo, ensure_ascii=False)
        items[F.KEY_BOARD] = json.dumps(board, ensure_ascii=False)
        msg = f'“{baslik}” şeması güncellendi ({len(spec["nodes"])} öğe, {len(spec["edges"])} bağlantı).'
        if spec.get('bagsiz'):
            msg += ' Dikkat: şunlar henüz hiçbir şeye bağlı değil: ' + ', '.join(spec['bagsiz']) + ' (baglantilar ile bağla).'
        sonuc.append(msg)
    F.duzenle(fn)
    return sonuc[0] if sonuc else 'Şema güncellenemedi.'


def sema_oku(a: dict) -> str:
    ad = _s(a, 'baslik')
    items = F.snapshot_oku()['items']
    if not ad:
        tablo = _sema_tablo(items)
        var = {str(q.get('id')): q for q in _gorunur_notlar(items)}
        liste = [f'- {var[k].get("title")} ({len(v.get("spec", {}).get("nodes", []))} öğe)' for k, v in tablo.items() if k in var]
        return ('Fikirler panosundaki şemalar:\n' + '\n'.join(liste)) if liste else 'Henüz şema yok. “… şemasını çiz” demen yeterli.'
    n, adaylar = _not_bul(items, ad)
    if n is None:
        return _bulunamadi(ad, adaylar)
    kayit = _sema_tablo(items).get(str(n.get('id')))
    ek_ = '' if kayit else '\n(Bu not BLOOM’un çizdiği bir şema değil; sema_guncelle ile değiştirilemez.)'
    return f'“{n.get("title")}”:\n' + str(n.get('text') or '')[:4000] + ek_


# --------------------------------------------------------------------------- yönlendirme
def calistir(islem: str, a: dict) -> str | None:
    """ek_fikir.arac'tan çağrılır. Tanınmayan işlem için None."""
    tablo = {
        'notlar': notlar, 'not_oku': not_oku, 'not_duzenle': not_duzenle, 'not_sil': not_sil, 'etiketle': etiketle, 'sabitle': sabitle, 'baglan': baglan, 'benzer': benzer,
        'fikir_gelistir': fikir_gelistir, 'fikri_goreve_cevir': fikri_goreve_cevir,
        'gorev_toplu': gorev_toplu, 'geciken': geciken, 'geciken_tasi': geciken_tasi, 'gorev_kategori': gorev_kategori,
        'hafta_oku': hafta_oku, 'hafta_duzenle': hafta_duzenle, 'hafta_sil': hafta_sil, 'bos_zaman': bos_zaman, 'planla': planla, 'plan_uygula': plan_uygula,
        'rutin_oku': rutin_oku, 'rutin_ekle': rutin_ekle, 'rutin_yap': rutin_yap, 'rutin_sil': rutin_sil,
        'gunluk_oku': gunluk_oku, 'gunluk_yaz': gunluk_yaz, 'kaynak_ekle': kaynak_ekle, 'kaynak_ara': kaynak_ara,
        'kategoriler': kategoriler, 'kategori_ekle': kategori_ekle, 'gozden_gecir': gozden_gecir,
        'sema_ekle': sema_ekle, 'sema_guncelle': sema_guncelle, 'sema_oku': sema_oku,
    }
    fn = tablo.get(islem)
    if fn is None:
        return None
    try:
        return fn(a)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        log('ek_fikir_arac: işlem hatası', islem, type(exc).__name__, str(exc)[:120])
        return f'Fikir Alanım “{islem}” işlemi şu an yapılamadı ({type(exc).__name__}).'
