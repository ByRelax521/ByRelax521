# BLOOM — JARVIS V4.6.2 kaynak snapshotı

BLOOM, eski adıyla JARVIS V4, Gemini Live tabanlı masaüstü asistanıdır. Bu depo, Google Drive'daki `JARVIS/_internal/jarvis` klasöründen alınan Python yama/kaynak dosyalarını, React/Vite HUD'u ve ilgili haritaları bir araya getirir.

## Bu depoda neler var?

- `jarvis/`: 104 Python modülü (ana paket ve `actions`, `audio`, `brain`, `tools`, `ui` alt paketleri).
- `web_hud/`: React 19 + TypeScript + Vite arayüzü.
- `hud_ek/`: BLOOM/JARVIS HUD için ek CSS/JavaScript varlıkları.
- `win_entry.py`: PyInstaller Windows giriş noktası.
- `docs/`: modül haritası, yama eşlemesi ve proje notları.
- `tests/`: kurtarılan yardımcı fonksiyonlar için ağ/API kullanmayan regresyon testleri.

## Önemli: kaynak kapsamı

`docs/OKU-BENI.txt` bu klasörü çalışan uygulamanın **salt okunur kaynak kopyası** olarak tanımlar: dağıtılan masaüstü uygulamasının ana kodu PyInstaller bayt kodunda çalışır; bu kaynak kopyası bazı yamalı modülleri ve yaklaşık %82 oranında eşleşen işlevleri içerir. Ayrıca 24 dosyada `WARNING: Decompyle incomplete` işareti vardır.

Bu nedenle bu depo şu anda **tek başına tam masaüstü uygulaması derlemek veya dağıtmak için yeterli değildir**. Orijinal, eksiksiz kaynak ağacı; kullanılan Python bağımlılıklarının sürüm listesi; PyInstaller tanımları ve varlık üretim adımları ayrıca sağlanıp doğrulanmalıdır. Buradaki kaynak düzeltmeleri yayımlanmış/önceden derlenmiş `.exe` dosyasını değiştirmez.

## HUD geliştirme ve test

Node.js 22 önerilir:

```bash
cd bloom/web_hud
npm ci
npm run dev -- --host 0.0.0.0
npm run build
npm run lint
```

Vite geliştirme sunucusu HUD'u tek başına sunar. Arayüzün `/api/*` çağrıları masaüstü Python çekirdeği tarafından karşılanır; Vite sunucusunda backend proxy'si yoktur. Dolayısıyla tam işlevler için eksiksiz masaüstü uygulamasının çalışması gerekir. `npm run build`, üretilen `dist/` klasörünü verir; bu çıktı Git'e eklenmez.

Python hedefi 3.12'dir:

```bash
python3.12 -m compileall -q bloom/jarvis bloom/win_entry.py
PYTHONPATH=bloom JARVIS_DATA_DIR=/tmp/bloom-test-data \
  python3.12 -m unittest discover -s bloom/tests -v
```

Testler Gemini API'sine bağlanmaz, mikrofon/kamera açmaz ve gerçek kullanıcı ayarlarına dokunmaz.

## Son doğrulama — 14 Kasım 2026

- `npm ci --no-audit --no-fund`: temiz kurulum başarılı (49 paket).
- `npm run build`: başarılı; Vite 8.3.8, 476 modül işlendi.
- `npm run lint`: başarılı, 0 hata ve `src/hands/synthetic.ts:30` satırında 1 iyileştirme uyarısı (`new Array(21)`).
- `npm audit`: tüm bağımlılık ağacında 0 açık güvenlik uyarısı (kullanılmayan `vite-plugin-pwa` kaldırıldı).
- Python regresyon testleri: 3/3 geçti (ayar, mikrofon veya ağ erişimi kullanmadan).
- Kaynak Python dosyaları güncel Python grameriyle tarandı; sözdizimi hatası bulunmadı. Bu çalışma alanında Python 3.12 bulunmadığından tüm çekirdeği Python 3.12 altında çalıştırmak mümkün olmadı; Python 3.11 ile tam `compileall` uygun bir doğrulama sayılmaz (kaynak 3.12 f-string dilbilgisini kullanıyor).
- Vite önizleme sunucusunda HTML ve React giriş modülü HTTP 200 döndürdü. Bu, masaüstü backend'inin veya Gemini/Windows ses-kamera özelliklerinin uçtan uca testi değildir.

### Test sırasında düzeltilen kaynak sorunları

- `index.html` içindeki Cloudflare Rocket Loader özniteliği Vite'ın giriş modülünü devre dışı bırakıyordu; standart `type="module"` kullanıldı ve sayfaya eklenmiş Cloudflare betiği kaldırıldı.
- PWA kullanılmadığı için güvenlik uyarıları taşıyan `vite-plugin-pwa` bağımlılığıyla eski giriş dosyasındaki service-worker kayıt/güncelleme kodu kaldırıldı.
- Otomatik konuşma dili için geçersiz `None` sözlük anahtarı, `language_codes` alanına düzeltildi.
- Türkçe ekin küçük harfli biçimi ve Windows mikrofon gizlilik sayfasını açan yol düzeltildi; bu üç davranış için regresyon testleri eklendi.
- Lint komutu `node_modules` içindeki üçüncü taraf dosyaları taramayacak şekilde sınırlandırıldı.

## Öncelikli geliştirme önerileri

1. **Eksiksiz ve yeniden üretilebilir kaynak:** decompiler uyarılarının bulunduğu kopya yerine, gerçek Python 3.12 kaynak ağacını, PyInstaller/build dosyalarını ve kilitlenmiş bağımlılık listesini ekleyin.
2. **Platform CI'si:** Python 3.12 testlerini Windows ve macOS işlerinde çalıştırın; izin, ses aygıtı, uygulama başlatma ve HUD–backend akışlarını donanım yerine mock'larla test edin.
3. **Daha geniş test kapsamı:** Gemini Live hata/yeniden bağlanma, araç izinleri, dosya işlemleri, hafıza gizliliği, mikrofon yaşam döngüsü ve güncelleme akışlarına birim ve entegrasyon testleri ekleyin.
4. **Bağımlılık ve varlık yönetimi:** Python bağımlılıklarını sürüm kilidiyle belirtin; el/kamera modellerini çevrimdışı kullanım için gerekiyorsa lisans, kaynak ve SHA-256 bilgileriyle paketleyin. Şu an HUD'daki bazı modeller uzak URL'den alınabiliyor.
5. **Lint uyarısı:** `synthetic.ts` içindeki uzunluğu belirtilen `new Array(21)` kullanımını daha açık bir dizi kurulumuyla değiştirin veya niyetini açıklayın.
6. **Gizli veri denetimi:** `.env`, API anahtarı, kullanıcı hafızası, günlük ve üretilmiş uygulama paketlerini GitHub'a eklemeden önce otomatik secret-scan ve release kontrolü çalıştırın.
