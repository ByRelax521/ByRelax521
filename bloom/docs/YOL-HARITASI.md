# BLOOM — Mark 2 yol haritası

Referans: github.com/halilozat/jarvis (Node sunucu + React; Abacus RouteLLM; tarayıcı/telefon). Yerel kopyası `referans/halilozat-jarvis/` (çalışma alanında, pakete girmez).

## Kararlar
- **Çekirdek Python kalıyor.** Referans proje sahne tabanlı bir sohbet uygulaması (yazı → TTS). BLOOM ise Gemini Live ile gerçek zamanlı ses, Windows pencere/ekran/uygulama kontrolü, wake word ve Fikir Alanı taşıyor. Bunları Node'a taşımak Windows'ta denenemeyen bir baştan yazım olurdu; kazanç yok, kayıp büyük.
- **Beyin Gemini Live kalıyor** (kullanıcı kararı). Kalite işi araç ve istem tarafında yapılıyor.
- **Referanstan alınan:** tasarım dili (çerçeveli kartlar, durum çipi, öneri çipleri, yuvarlak komut çubuğu), "karmaşık ayarı kendi yönetsin" yaklaşımı (otomatik araç kullanımı), değişmeyen istemin başta/değişenin sonda durması ilkesi.

## Aşamalar
| # | Aşama | Durum |
|---|---|---|
| 1 | Mark 2 ana ekran (kartlar, orb halkaları, durum yazısı, öneri çipleri, mikrofon/kamera ikonları; Ctrl+Shift+M ile eski görünüm) | **Bitti (3.11.0)** |
| 1b | Yetenek / MCP / Konsey otomatik kullanım ilkeleri | **Bitti (3.11.0)** (istem düzeyinde) |
| 2 | PANEL'deki 7 sekmeyi sadeleştir (Odak · Araçlar&Yetenekler · Gelişmiş); eski hikâye DOM/JS artıklarını HUD'dan temizle | **Bitti (3.11.1)**: 3 sekme; temiz HUD dosyaları `BLOOM-EK/hud-temiz/` (isteğe bağlı, `UYGULA.ps1`) |
| 3 | Yeni kartlar: GÜNDEM (haber başlıkları), döviz (TCMB), hava; SPOTIFY şu an çalan | **Kısmen bitti (3.12.0)**: haber + döviz + hava jarvis-main ekranında; Spotify kartı yok |
| 3w | jarvis-main arayüzünü (React, Mark 2) BLOOM'un ekranı yap (yol A: iframe + yerel köprü) | **Bitti (3.12.0)**, yalnızca başsız Chromium'da test edildi; Ctrl+Shift+W ile Mark 2 katmanına dönülür |
| 4 | Araç şemalarını sadeleştir / birleştir, istem sırasını önbelleğe uygun düzenle | Sırada |
| 5 | El kontrolü / yüz kilidi | **El kontrolü bitti (3.12.0, H tuşu / EL düğmesi)**; yüz kilidi bağlanmadı; BLOOM ayarları (AYARLAR/PANEL/MODELLER) hâlâ HUD katmanlarında, React'e taşınmadı |

## 3.12.0 — jarvis-main ekranı
| Parça | Dosya | Test |
|---|---|---|
| React arayüzü (kaynak) | `web_hud/src/bloom/{store.ts,BloomMark2.tsx,BloomApp.tsx,bloom.css}`, `web_hud/src/{mark2,hands}/` (jarvis-main'den) | `tsc`, `test_r312_hud` |
| Derleme → exe'ye gömme | `cd web_hud && npx vite build` → `araclar/ek_web_uret.py` → `ek_web_dosya.py` (üretilmiş) | `test_r312_web` |
| Yerel hizmet (127.0.0.1:47834), pano, kitaplık | `kaynak/jarvis/ek_web.py`, `ek_pano.py` (Open-Meteo, TCMB, RSS) | `test_r312_web` |
| HUD ↔ iframe köprüsü (postMessage) | `hud_ek/bloom-web.js/.css` → `ek_hud.py`; `ek.py` (`ek_web_adres`, ilk paneller) | `test_r312_hud` |
| El kontrolü varlıkları (wasm + 2 model) | `el-varliklari/` (exe yanında), `ek_web.el_klasorleri()` | `test_r312_hud` (5. bölüm) |
Akış: Python `jarvis.state/line/panel/level/ekDurum/ekCanli/mic/webcam/sleep` çağrıları HUD'da sarılır ve iframe'e iletilir; iframe'in komutları (mikrofon, kamera, uyku, ayarlar, panel, model, metin, F4/F6) gerçek HUD düğmelerine çevrilir. Ses/mikrofon/kamera Python'dadır.
Güvenlik ağı: iframe 6 sn içinde "hazir" demezse kaldırılır ve Mark 2 katmanı kalır.

## 3.12.1 — sürüm komutu ve LOG
| Parça | Dosya | Test |
|---|---|---|
| `--version` / `--help` / `--log` (yerel, modele gitmez), araç listesi, günlük maskeleme | `kaynak/jarvis/ek_surum.py` (`SURUM`; `ek.bagla` kancası) | `test_r312_surum` |
| LOG paneli (Mark II) + `/api/surum`, `/api/ozellikler`, `/api/log` | `web_hud/src/bloom/LogPanel.tsx`, `ek_web.py` | `test_r312_hud` |
Yeni sürümde `ek_surum.SURUM` sabitini güncelle.
