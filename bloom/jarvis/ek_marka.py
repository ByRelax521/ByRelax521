"""BLOOM — ad tutarlılığı: model kendine eski adla (JARVIS) seslenmesin.

Sorun: ekrandaki yazıları tarayıcı katmanı çeviriyordu ama MODELİN GÖRDÜĞÜ metinlerin çoğu çevrilmiyordu:
  * önceki konuşmalar (eski cevaplarda "Ben JARVIS" yazar), öğrenilenler (dersler), kullanıcı belleği, durum/zaman blokları,
  * "JARVİS’in" (noktalı İ, kıvrık kesme) gibi yazımlar ve "JARVIS uygulaması" gibi uygulama adını koruyan istisnalar.
Model bunları görüp kendine JARVIS demeyi sürdürüyordu. Burada modele giden metinler (sistem istemi, araç açıklamaları, ek bloklar) tek noktada düzeltilir.

KORUNANLAR (gerçek ad/yol olduğu için DEĞİŞMEZ): JARVIS V4 (veri klasörü), JARVIS-Kod, JARVIS Dosyaları, JARVIS.exe, JARVIS-Fikir, JARVIS_* ortam değişkenleri,
küçük harfli `jarvis` (paket/klasör/kimlik), "jarvis" yolları. Kayıtlı veriye (geçmiş, bellek) DOKUNULMAZ: yalnızca modele gidişte çevrilir.
Araç SONUÇLARI çevrilmez (dosya adı gibi gerçek veriyi bozmasın).
"""

from __future__ import annotations
import importlib
import re
from . import brand
from .log import log

KORUNAN = re.compile(r'JARV[Iİ]S(?:\s+V4|-Kod|-Fikir|-orijinal|-EK|\.exe|\s+Dosyaları|\s+Ekran Görüntüleri)|JARVIS_[A-Z_]+|Documents/JARVIS|Belgeler/JARVIS')
ADLAR = re.compile(r'(?<![\w.\\/=-])(J\.A\.R\.V\.I\.S|JARV[Iİ]S|Jarv[iİı]s)(?:([\'’])([^\W\d_]+))?(?:(\s+)(de|da|DE|DA)(?!\w))?(?!\w)')
HIZLI = re.compile(r'J\.?A\.?R\.?V\.?[Iİiı]\.?S', re.I)
FILM = re.compile(r"Marvel|Stark|Iron Man|Avengers|Yenilmezler|eski adın JARVIS")     # son: kimlik_blogu satırı (kasıtlı eski ad)
_KUR = {'ok': False}


def ad() -> str:
    try:
        return brand.name('jarvis')
    except Exception:
        return 'BLOOM'


def duzelt(text: str) -> str:
    """Metindeki eski adı (JARVIS / Jarvis / JARVİS / J.A.R.V.I.S, ekleriyle) şimdiki adla değiştirir; korunan gerçek adlara dokunmaz."""
    if not text or not isinstance(text, str) or not HIZLI.search(text):
        return text
    yeni_ad = ad()
    if brand.upper(yeni_ad).replace('İ', 'I') == 'JARVIS':
        return text                              # kullanıcı adını yine JARVIS yaptıysa dokunma
    yer: list[str] = []

    def sakla(m: re.Match) -> str:
        yer.append(m.group(0))
        return f'\x00{len(yer) - 1}\x00'

    def sub(m: re.Match) -> str:
        tok = m.group(1)
        yeni = yeni_ad if (tok.isupper() or '.' in tok) else brand.title(yeni_ad)
        return brand._reword(yeni, m.group(2) or '', m.group(3) or '', m.group(4) or '', m.group(5) or '')

    sat = []
    for ln in text.split('\n'):
        if FILM.search(ln) or not HIZLI.search(ln):
            sat.append(ln)
            continue
        ln = KORUNAN.sub(sakla, ln)
        ln = ADLAR.sub(sub, ln)
        sat.append(re.sub('\x00(\\d+)\x00', lambda m: yer[int(m.group(1))], ln))
    return '\n'.join(sat)


def kimlik_blogu() -> str:
    """İstemin SONUNA konur (düzeltmeden sonra): modelin kendi adı."""
    a = ad()
    return f"[ADIN] {a} (eski adın JARVIS'ti; artık kullanma; öyle seslenene düzeltmeden yanıtla)."


def kur() -> None:
    """Modele giden metinleri düzelten kancalar (kapalı/gereksizse hiçbir şey değiştirmez)."""
    if _KUR['ok']:
        return
    try:
        from . import personas
        if not getattr(personas.system_instruction, '_ek_marka', False):
            orig = personas.system_instruction

            def sistem(*a, **k):
                return duzelt(orig(*a, **k))
            sistem._ek_marka = True
            personas.system_instruction = sistem
        R = importlib.import_module('.tools.registry', __package__)
        if not getattr(R.Registry.to_gemini, '_ek_marka', False):
            orig_tg = R.Registry.to_gemini

            def to_gemini(self, *a, **k):
                return [dict(d, description=duzelt(d.get('description', ''))) if isinstance(d, dict) else d for d in orig_tg(self, *a, **k)]
            to_gemini._ek_marka = True
            R.Registry.to_gemini = to_gemini
        _KUR['ok'] = True
    except Exception as exc:
        log('ek: marka kancaları kurulamadı', type(exc).__name__, str(exc)[:80])
