"""BLOOM — kendini geliştirme: "bunu yapamıyorum" demek yerine eksiği kaydet, yetenek yaz ya da Hermes'e yaptır.

Güvenli döngü (hiçbir adım kullanıcıdan habersiz kod/kurulum yapmaz):
  1) EKSİK KAYDI   gelisim(kaydet): neyin yapılamadığı ek/gelisim.jsonl dosyasına yazılır (yerel, en çok 200 kayıt).
  2) KENDİ YETENEĞİ talimatla çözülebilen iş için yetenek_yonet(yaz) ile SKILL.md yazar (betik çalıştırılmaz).
  3) HERMES        kod/kurulum/çok adımlı iş için gelisim(hermese_ver): ÖNİZLEME gösterir; kullanıcı onaylarsa Hermes'e gider.
                   Hermes yeteneği kendi klasörüne yazar; sonra hermes(yetenek_listele/yetenek_al) ile (yine önizleme + onay) alınır.
Bloom kendi program dosyalarını (exe) DEĞİŞTİRMEZ: paketli uygulama kendini yeniden yazamaz; gelişme yetenek (talimat) ve
Hermes'in ürettiği araçlar üzerinden olur.
"""

from __future__ import annotations
import json
import re
import time
from pathlib import Path
from .log import log

EN_COK = 200
HERMES_TALIMAT = (
    'Bloom adlı sesli asistan bir işi yapamadı ve senden bir YETENEK (Agent Skills biçimi) istiyor.\n'
    'İstenen: {istek}\n{ayrinti}\n'
    'Yap: ~/.hermes/skills altında "bloom-<kısa-ad>" klasörü aç; içine SKILL.md yaz (YAML başlık: name, description; ardından Bloom\'un '
    'adım adım izleyeceği Türkçe talimat). Gerekirse aynı klasöre yardımcı betikleri koy ama bunları KENDİN çalıştırıp doğrula.\n'
    'Kurallar: Bloom\'un program dosyalarına dokunma; kullanıcının dosyalarını silme/değiştirme; parola ve anahtar yazma; '
    'yıkıcı ya da paralı adım için onay iste. Bitince yalnızca klasör adını ve ne yaptığını 3 cümleyle söyle.')


def _veri() -> Path:
    from . import paths
    return Path(paths.DATA_DIR)


def _oku() -> list[dict]:
    p = _veri() / 'ek' / 'gelisim.jsonl'
    out = []
    try:
        for ln in p.read_text('utf-8').splitlines():
            try:
                d = json.loads(ln)
                if isinstance(d, dict):
                    out.append(d)
            except ValueError:
                pass
    except OSError:
        pass
    return out


def kaydet(istek: str, neden: str = '') -> str:
    istek = ' '.join(str(istek or '').split())[:300]
    if len(istek) < 4:
        return 'Hata: neyin yapılamadığı yazılmadı.'
    p = _veri() / 'ek' / 'gelisim.jsonl'
    kayit = _oku()
    kayit.append({'t': int(time.time()), 'istek': istek, 'neden': ' '.join(str(neden or '').split())[:300], 'durum': 'acik'})
    kayit = kayit[-EN_COK:]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(json.dumps(k, ensure_ascii=False) for k in kayit) + '\n', 'utf-8')
    except OSError as exc:
        return f'Hata: kaydedilemedi ({type(exc).__name__}).'
    return f'Eksik kaydedildi: “{istek}”. Çözüm için: kendi yeteneğimi yazabilirim ya da Hermes\'e yaptırabilirim (onayınla).'


def liste() -> str:
    k = [x for x in _oku() if x.get('durum') == 'acik']
    if not k:
        return 'Kayıtlı açık eksik yok.'
    return 'Açık eksikler:\n' + '\n'.join(f'{i + 1}. {x["istek"]}' + (f' ({x["neden"]})' if x.get('neden') else '') for i, x in enumerate(k[-15:]))


def gorev_metni(istek: str, ayrinti: str = '') -> str:
    istek = ' '.join(str(istek or '').split())[:600]
    ayr = ' '.join(str(ayrinti or '').split())[:1500]
    return HERMES_TALIMAT.format(istek=istek, ayrinti=('Ayrıntı: ' + ayr + '\n') if ayr else '')


def hermese_ver(istek: str, ayrinti: str = '', onay: bool = False) -> str:
    if len(' '.join(str(istek or '').split())) < 8:
        return 'Hata: Hermes\'e ne yaptıracağım açık değil (istek yaz).'
    from . import ek_hermes
    if not ek_hermes.bagli_mi():
        return ('Hermes bağlı değil, bu yüzden ona devredemem. hermes(eylem=kurulum) ile bağlama adımlarını söyleyebilirim; '
                'şimdilik kendi yeteneğimi yazmayı deneyebilirim (yetenek_yonet yaz).')
    gorev = gorev_metni(istek, ayrinti)
    if not onay:
        return ('ÖNİZLEME (gönderilmedi). Hermes\'e şunu yaptıracağım: yeni bir yetenek klasörü yazması (' + ' '.join(istek.split())[:200] +
                '). Program dosyalarıma dokunmayacak; yıkıcı adımda sana soracak. Kullanıcıya özetle; açıkça "evet" derse onay=true ile tekrar çağır.')
    sonuc = ek_hermes.gonder(gorev)
    kaydet(istek, 'Hermes\'e verildi')
    return sonuc + ' Bitince hermes(yetenek_listele) ile yeni yeteneğe bakıp yetenek_al (önizleme + onay) ile alırız.'


def istem_blogu() -> str:
    acik = [x for x in _oku() if x.get('durum') == 'acik']
    ek = f' Kayıtlı {len(acik)} açık eksik var (gelisim liste).' if acik else ''
    return ('[KENDİNİ GELİŞTİRME]\nYapamadığın işte yalnızca "yapamam" deme: talimatla çözülürse yetenek_yonet(yaz) ile yetenek yaz; kod/kurulum/çok '
            'adımlıysa gelisim(hermese_ver) öner (önizleme + açık onay şart); eksiği gelisim(kaydet) ile not düş. Program dosyalarını değiştiremezsin.' + ek)


def arac(a, _c=None) -> str:
    a = a or {}
    e = str(a.get('eylem') or 'liste').lower()
    if e == 'kaydet':
        return kaydet(a.get('istek'), a.get('neden'))
    if e == 'liste':
        return liste()
    if e == 'hermese_ver':
        return hermese_ver(a.get('istek'), a.get('ayrinti'), bool(a.get('onay')))
    return 'Hata: bilinmeyen eylem. kaydet | liste | hermese_ver.'
