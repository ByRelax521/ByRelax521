"""BLOOM — BLOOM ile gelen hazır yetenekler (özgün Türkçe yazımlar) ve önerilen GitHub depoları.

Bu yetenekler ilk çalıştırmada kullanıcının yetenek klasörüne bir kez yazılır (kullanıcı silerse geri gelmez, düzenlerse ezilmez).
Fikir kaynakları (metin KOPYALANMADI; yalnızca yöntemin adı/fikri alındı):
  obra/superpowers (MIT), addyosmani/agent-skills (MIT), mattpocock/skills (MIT) — hata ayıklama, planlama, doğrulama alışkanlıkları;
  multica-ai/andrej-karpathy-skills — "küçük, cerrahi değişiklik" ilkesi (depoda lisans yok → yalnızca fikir);
  morluto/rea (MIT) — tersine mühendislik iş akışı ve kullanım sınırları (DISCLAIMER.md özeti).
"""

from __future__ import annotations

SURUM = 1

TOHUM: dict[str, dict] = {
    'sistematik-hata-ayiklama': {
        'aciklama': 'Bir şey bozuk/hata veriyor: tahmin etmeden, kanıta dayalı adım adım hata ayıklama.',
        'fikir': 'obra/superpowers (MIT)',
        'govde': '''# Sistematik hata ayıklama

1. **Yeniden üret.** Hatayı tam olarak nasıl tetikleyeceğini bul (adımlar, girdi, ortam). Üretemiyorsan kullanıcıdan tek net bilgi iste.
2. **Hata iletisini sonuna kadar oku.** Dosya, satır, hata türü, son çağrı. İlk satıra bakıp tahmin yürütme.
3. **Neyin değiştiğine bak.** "Daha önce çalışıyordu" ise ne değişti: sürüm, ayar, dosya, ağ, limit/kota?
4. **Tek bir varsayım kur ve tek şeyle sına.** Aynı anda birden çok değişiklik yapma; yoksa neyin işe yaradığı anlaşılmaz.
5. **Kanıt topla:** log, değişken değeri, küçük bir deneme. "Büyük olasılıkla" ile düzeltme yazma.
6. **Kök nedeni düzelt, belirtiyi değil.** Hatayı yutan try/except ya da sonsuz yeniden deneme çözüm değildir.
7. **Doğrula:** düzeltmeden sonra aynı adımlarla yeniden dene; yan etki var mı bak.
8. Üç denemede çözülmediyse dur, varsayımlarını yeniden sorgula ve kullanıcıya ne bildiğini/bilmediğini dürüstçe söyle.
''',
    },
    'once-planla': {
        'aciklama': 'Çok adımlı ya da belirsiz iş istendiğinde: önce kısa plan ve başarı ölçütü, sonra uygula.',
        'fikir': 'obra/superpowers (MIT)',
        'govde': '''# Önce planla, sonra yap

1. **Amacı tek cümleyle yaz** ve "bitti" neye benzer (ölçülebilir ölçüt).
2. Eksik olan ve işi gerçekten değiştiren en çok 1-2 şeyi sor; geri kalanı makul varsayımla doldur ve varsayımı söyle.
3. **3-6 adımlık plan** çıkar; her adımın çıktısı belli olsun. Büyük adımı böl.
4. Riskli/geri alınamaz adımları işaretle, onları yapmadan önce kullanıcıdan onay al.
5. Uzun sürecek parçaları arka plan araçlarına (araştırma, kod projesi) ver; sen planı izle.
6. Her adım bitince kısa bildir; plan değişirse nedenini söyle.
Basit, tek adımlık işte plan kurma; doğrudan yap.
''',
    },
    'bitirmeden-dogrula': {
        'aciklama': '"Tamam/bitti" demeden önce: yapıldığını kanıtla, doğrulayamadığını söyle.',
        'fikir': 'obra/superpowers (MIT)',
        'govde': '''# Bitirmeden doğrula

"Tamam" demeden önce şunları yap:
1. **İstenen şey ile yapılan şeyi karşılaştır.** İsteğin her maddesi karşılandı mı?
2. **Kanıt göster:** çalıştırdın mı, dosya var mı, araç sonucu ne döndü? Aracın döndürdüğü sonucu aynen esas al; uydurma.
3. Kontrol edemediğin şeyi açıkça söyle ("bunu deneyemedim", "yalnızca kodu yazdım, çalıştırmadım").
4. Araç hata ya da kısmi sonuç verdiyse "başardım" deme; ne olduğunu ve sonraki adımı söyle.
5. Kullanıcıya sonucu kısa ver: ne yapıldı, nerede, nasıl denendi, kalan risk.
''',
    },
    'derin-dusun-karar': {
        'aciklama': 'Karar/seçim/strateji sorulduğunda: ölçütlü karşılaştırma ve net öneri.',
        'fikir': 'karar analizi yöntemleri (genel)',
        'govde': '''# Karar ver: ölçütlü karşılaştırma

1. Kararı ve **son tarihi/kısıtı** netleştir (bütçe, süre, geri alınabilirlik).
2. 2-4 gerçekçi seçenek yaz (hiçbir şey yapmamak dahil).
3. Kullanıcının önemsediği 3-5 **ölçüt** belirle (maliyet, süre, risk, öğrenme, esneklik); ağırlık ver.
4. Her seçeneği ölçütlerle kısaca puanla; en büyük riski ve "yanılırsam ne olur" kısmını yaz.
5. **Net bir öneri** ver ve nedenini tek paragrafta söyle; belirsiz yeri ve neyin bilinmesi önerini değiştirirdi ise onu belirt.
6. Güncel veriye bağlıysa (fiyat, haber, sürüm) önce arastir aracıyla bak, tahmin yürütme.
Cevabı kısa tut; tablo yerine seslendirmeye uygun düz cümleler kullan.
''',
    },
    'cerrahi-degisiklik': {
        'aciklama': 'Var olan kod/belge değişikliğinde: en küçük değişiklik, ilgisiz yere dokunma.',
        'fikir': 'Karpathy kodlama ilkeleri (yalnızca fikir; depoda lisans yok)',
        'govde': '''# Cerrahi değişiklik

- **Önce oku**, sonra değiştir. Mevcut yapıyı, adlandırmayı ve üslubu koru.
- **Yalnızca istenen şeyi** değiştir; "ayrıca şunu da düzelteyim" diye ilgisiz yere dokunma. Gördüğün başka sorunu değiştirmeden söyle.
- En basit çalışan çözümü seç; gereksiz soyutlama, ek bağımlılık ya da büyük yeniden yazım ekleme.
- Belirsiz bir yer varsa varsayımını açıkça söyle; yanlış varsayım pahalıysa önce sor.
- Değişikliği küçük parçalarla yap ve her parçadan sonra doğrula; eski hali geri alınabilir kalsın (yedek).
- Sonunda tam olarak neyin neden değiştiğini iki-üç cümleyle özetle.
''',
    },
    'gorev-rutin-plani': {
        'aciklama': 'Görev, rutin ve haftalık plan isteklerinde: önceliklendir, küçük adımlara böl, boş saatlere yerleştir, günlük alışkanlık kur, haftalık gözden geçir (Fikir Alanım aracıyla).',
        'fikir': 'Eisenhower matrisi, 2 dakika kuralı, alışkanlık istifleme (James Clear), haftalık gözden geçirme (GTD) — yöntem adları; metin özgündür. Aday depo: afeezadebayo/planning-task-management-skills (CC BY 4.0, kopyalanmadı)',
        'govde': '''# Görev, rutin ve plan (Fikir Alanım)

Görevler ile rutinler artık Fikir Alanım'ın aynı "Görev & Rutin" sekmesindedir; hepsini `fikir` aracıyla kendin yap.

## 1. Önce yakala, sonra düzenle
- Kullanıcı bir sürü şey sayarsa `fikir(islem=gorev_toplu, metin=...)` ile hepsini tek seferde ekle; soru sorup oyalama.
- Tarih/saat söylendiyse yaz, söylenmediyse uydurma. Belirsiz tek şey varsa tek kısa soru sor.

## 2. Önceliklendir (Eisenhower)
- Acil + önemli: bugün. Önemli ama acil değil: haftaya yerleştir (en çok değer burada). Acil ama önemsiz: kısa tut ya da devret. İkisi de değil: sil ya da sor.
- Bugüne en fazla 3 ana görev koy; fazlası plan değil dilek listesidir. Kullanıcıya bunu nazikçe söyle.

## 3. Küçült
- Büyük görevi ilk adımı 15-30 dakikayı geçmeyecek parçalara böl. "Rapor yaz" yerine "ana başlıkları çıkar".
- 2 dakikada biten işi listeye yazma, hemen yaptır ya da yaptığını söyle.

## 4. Zamana yerleştir
- Önce `fikir(islem=geciken)` ile eski işleri gör; kullanıcı isterse `geciken_tasi` ile bugüne ya da yarına taşı, sormadan silme.
- `fikir(islem=planla, gun=...)` boş aralıkları ÖNERİR, yazmaz. Kullanıcı "tamam" deyince `plan_uygula` yaz. Önerinin ne olduğunu kısaca oku.
- Zor/derin işi kullanıcının en enerjik saatine, ufak işleri boşluklara koy; araya mola payı bırak.

## 5. Rutin kur
- Önce `rutin_oku` ile mevcut rutinleri gör; aynısını ikinci kez ekleme.
- Yeni rutin küçük başlasın (2 dakikalık sürüm: "1 sayfa oku", "1 bardak su"). Mevcut bir alışkanlığa bağla: "kahveden sonra ilaç".
- Tek seferde en fazla 1-2 yeni rutin öner. Tamamlayınca `rutin_yap`; kaçırınca suçlama, bir sonraki kolay adımı söyle ("iki gün üst üste kaçırma").

## 6. Haftalık gözden geçirme
- İstendiğinde `fikir(islem=gozden_gecir, kapsam=hafta)`: ne bitti, ne gecikti, neden. Sonra: kalanı taşı, anlamsızı sil, gelecek hafta için en önemli 3 işi seç.
- Sonucu kısa ve sesli okunur yaz: sayı + tek öneri. Uzun liste okuma.

## Dürüstlük
- Araç "eklendi" demeden eklendi deme; hata varsa olduğu gibi söyle. Kullanıcının verisini onaysız toplu silme.
''',
    },
    'rea-tersine-muhendislik': {
        'aciklama': 'exe/Electron/JS/APK analizi, tersine mühendislik istenince: REA (mcp) ile yasal analiz.',
        'fikir': 'morluto/rea (MIT) — iş akışı ve sorumlu kullanım sınırları',
        'govde': '''# REA ile tersine mühendislik (mcp aracı)

## Önce sınırlar (atlama)
Yalnızca: **kendi yazılımı**, yetkili olduğu yazılım, güvenlik araştırması, zararlı yazılım/olay analizi, birlikte çalışabilirlik, CTF/eğitim, koruma amaçlı arşivleme.
**Yapma:** DRM/lisans/oyun hilesi/anti-cheat atlatma, kimlik doğrulama ya da bot korumasını aşma, başkasının korumalı kodunu/varlıklarını kopyalayıp yeniden dağıtma. İstek buna benziyorsa kibarca reddet, yasal bir alternatif öner. Emin değilsen kullanıcıya yazılımın kime ait olduğunu ve amacı sor.

## Kurulum (bir kez)
1. `mcp(eylem=sunucular)`. REA yoksa `mcp(eylem=kur_rea)`: önizleme gelir (Node.js 22.23.4+/24.22.1+ gerekir; yoksa kullanıcıya nodejs.org'dan Node 24 LTS kurmasını söyle). Kullanıcı onaylarsa `onay=true`.
2. Yerel exe/dll gibi ikili analizi kullanıcının KENDİ Ghidra/Hopper/IDA kurulumunu ister; Electron/JS/APK incelemesi çoğunlukla ek program istemez. Ghidra yoksa bunu dürüstçe söyle.

## İş akışı
1. Hedefi sor/doğrula: dosya yolu ve amaç (ne öğrenmek istiyor?).
2. `mcp(eylem=ara, sorgu="…")` ile İngilizce anahtar kelimelerle araç bul (ör. "javascript application", "strings", "decompile", "call graph", "overview").
3. `mcp(eylem=sema, arac=…)` ile girdi alanlarını oku; argümanları şemaya göre ver (ör. yol alanı `input_path`).
4. Genel görünümle başla (özet/envanter), sonra ilgili işlev, dize ya da çağrı grafiğine in; her bulguyu araç çıktısına dayandır.
5. Uzun çağrılar arka plana geçer; `isler` ile izle, bitince sonucu anlat.
6. Tüm çıktı dosyaya yazılır (yolu söylenir); özet çıkar, ham JSON'u sesli okuma. Rapor istenirse Fikir Alanım'a not yaz.
7. Bulguyu "kanıtlı / çıkarım / bilinmiyor" diye ayır. Araç hata verdiyse olduğu gibi söyle, uydurma.
''',
    },
}

ONERILER = '''ÖNERİLEN GITHUB DEPOLARI (yıldız sayıları 1 Kasım 2026'da GitHub API'den okundu; BLOOM'a kurmak için yetenek_yonet kur = ÖNİZLEME + onay):
YETENEK (SKILL.md) DEPOLARI — talimat yeteneği olarak kurulabilir; betikler (scripts/) kurulmaz, çalıştırılmaz:
1. obra/superpowers (~310 bin ★, MIT): beyin fırtınası, plan yazma/uygulama, test-önce geliştirme, sistematik hata ayıklama. Kurulum: kaynak=github.com/obra/superpowers (secim ile tek yetenek seç).
2. mattpocock/skills (~309 bin ★, MIT): küçük, birleştirilebilir mühendislik yetenekleri.
3. addyosmani/agent-skills (~112 bin ★, MIT): yazılım mühendisliği iş akışları (kod inceleme, test, güvenlik, performans).
4. JuliusBrussee/caveman (~117 bin ★, Apache-2.0): çok kısa ve jetonsuz konuşma tarzı. Dikkat: BLOOM'un sesli, sohbet üslubunu bozabilir.
5. nextlevelbuilder/ui-ux-pro-max-skill (~144 bin ★, MIT): arayüz/UX tasarım bilgisi — web sayfası yazarken işe yarar.
6. anthropics/skills (~186 bin ★; depo genelinde lisans yok, yetenek başına değişir): docx/pdf/pptx/xlsx yetenekleri betik kullandığı için BLOOM'da (betik çalıştırmaz) eksik çalışır; yalnızca talimat odaklı olanlar uygundur.
7. Dizinler (aramak için): ComposioHQ/awesome-claude-skills, hesreallyhim/awesome-claude-code, VoltAgent/awesome-agent-skills — listelerdir, tek tek yeteneği seçip kur.
BLOOM ZATEN BUNLARDAN ESİNLENEN ÖZGÜN YETENEKLERLE GELİR: sistematik-hata-ayiklama, once-planla, bitirmeden-dogrula, derin-dusun-karar, cerrahi-degisiklik, rea-tersine-muhendislik, gorev-rutin-plani (Fikir Alanım görev/rutin planlama).
MCP SUNUCULARI (mcp aracıyla; komut bilgisayarında çalışır, önizleme + onay şart; Node.js gerekir):
- morluto/rea (MIT): tersine mühendislik — mcp(eylem=kur_rea).
- modelcontextprotocol/servers (~92 bin ★): ör. dosya sistemi sunucusu: mcp(eylem=ekle, ad=dosyalar, komut="npx -y @modelcontextprotocol/server-filesystem C:/Belgeler") — yalnızca verdiğin klasöre erişir.
- microsoft/markitdown (~193 bin ★, MIT): PDF/Office/HTML'yi Markdown'a çevirir (MCP sürümü Python/uv ister).
- browser-use/browser-use (~120 bin ★, MIT): tarayıcı otomasyonu — ağır; ayrı kurulum ister, şimdilik önerilmez.
Lisans notu: lisansı olmayan depolardan (anthropics/skills genel, andrej-karpathy-skills) metin kopyalanmaz; yalnızca önerilir ya da fikri özgün yazılır.'''


KALDIR = {'satranc-ekran': ('ekran(tahta, sol_alt', 'tahta_kur')}      # kaldırılan özellik: kullanıcı değiştirmediyse eski tohum silinir


def tohumla() -> list[str]:
    """Hazır yetenekleri bir kez yazar. Döner: bu çağrıda yazılanların adları."""
    import json
    import time
    from . import ek_yetenek as Y
    from .log import log
    yazilan: list[str] = []
    isaret = Y.kok() / '.tohum.json'
    try:
        kayit = json.loads(isaret.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        kayit = {}
    gorulen = set(kayit.get('adlar') or [])
    for ad, izler in KALDIR.items():
        try:
            dosya = Y.kok() / ad / 'SKILL.md'
            if dosya.exists() and any(iz in dosya.read_text(encoding='utf-8') for iz in izler):
                Y.sil(ad)
        except Exception as exc:
            log('ek_yetenek: eski tohum silinemedi', ad, exc)
    for ad, t in TOHUM.items():
        if ad in gorulen:
            continue
        gorulen.add(ad)
        if (Y.kok() / ad).exists():
            continue
        try:
            metin = f'---\nname: {ad}\ndescription: {json.dumps(t["aciklama"], ensure_ascii=False)}\n---\n\n{t["govde"]}'
            Y._yaz(ad, {'SKILL.md': metin.encode('utf-8')}, 'BLOOM ile gelir — fikir kaynağı: ' + t['fikir'])
            yazilan.append(ad)
        except Exception as exc:
            log('ek_yetenek: tohum yazılamadı', ad, exc)
    try:
        isaret.write_text(json.dumps({'surum': SURUM, 'adlar': sorted(gorulen), 'zaman': int(time.time())}), encoding='utf-8')
    except OSError:
        pass
    return yazilan
