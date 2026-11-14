# BLOOM (eski adı JARVIS V4) — Kontrol Haritası

Durum: 30 Ekim 2026. Kaynak: senin `JARVIS.exe` dosyan (12.692.038 bayt, PyInstaller + Python 3.12). Hiçbir şey tahmin edilmedi; her satırın nasıl doğrulandığı yazıyor.

## 1. Elimizde ne var (ve ne kadarına güvenebilirsin)

| Parça | Durum |
|---|---|
| `JARVIS.exe` içinden çıkardığım **özgün bayt kodu** (76 modül) | Gerçeğin kendisi. Yapay zekâ/insan yorumu yok. |
| `kaynak/` (okunur Python kaynağı) | Arkadaşının decompile'ı + benim düzeltmelerim. **1738 fonksiyonun 1426'sı (%82) özgün bayt koduyla birebir aynı** (`araclar/dogrula.py` kanıtlıyordu; temizlikte silindi). Kalan 312'si okunur ama **hatalı olabilir** (örnek: `notes.delete` içinde bir koşul ters çevrilmişti; `notes.load/add` düzelttim). Hangileri olduğu `kaynak/_INDEKS.tsv` içinde `FARK` olarak işaretli. |
| Yeniden paketleme (`araclar/insa.py`) | **Kanıtlı:** yama vermezsem çıkan exe orijinalle **bayt bayt aynı**. Yamalı üretilen exe'nin içindeki modüller Linux'ta gerçek PYZ'den yüklenip çalıştırıldı (notes testi, özgünle aynı sonuç). |
| Windows'ta açılış testi | **YAPILAMADI** (burada Windows yok). Bu yüzden her yamalı exe'ye karşılık eski `JARVIS.exe` yedeği kalacak; ilk açılış testini sen yapacaksın. |

### Yamalama yöntemi (neden güvenli)
Değiştirmediğim her fonksiyon **özgün bayt koduyla kalır**. Sadece elle yazıp derlediğim fonksiyonlar değişir. Yani decompile'daki %18'lik hata payı çalışan uygulamaya sızmaz; yalnızca o fonksiyonları düzenlemek istediğimde önce `araclar/fark.py` ile özgün bayt koduna bakıp aynısını yeniden kurarım.

## 2. Hangi özellik nerede?

Genel akış: `win_entry` → `jarvis.ui.win_window` (pencere, pywebview) → `jarvis.app.App` (her şeyi yöneten sınıf; HUD'dan gelen olaylar `App.handle`) → `jarvis.brain.gemini_live.GeminiLiveBrain` (Gemini Live oturumu) → araçlar (`jarvis.tools.*`, `jarvis.actions.*`).

HUD ve istem dosyaları **ayrı, düzenlenebilir dosyalardır** (exe'ye gömülü değil): `hud.js` (7391 satır), `hud.css`, `index.html`, `prompts/base.md`. Görsel işlerin çoğu exe'ye hiç dokunmadan yapılır.

| İstediğin | Yer | Not |
|---|---|---|
| **Mikrofon/Sustur düğmesi taşımak** | HUD: iki düğme: `#set-mic` ve `#t-mic` (`hud.js` satır ~5426 ve ~5553), ortak işlev `setMic()` (~5546), F4 kısayolu (~7141); yerleri `index.html`'de | Yalnız HUD işi; exe gerekmez. |
| **Sohbet belleği / geçmiş** | Konuşma metni zaten `App.on_transcript` (app.py:118, bayt kodu doğrulandı) üzerinden geçiyor ama **diske yazılmıyor**. Oturum kimliği (`_resume_handle`) yalnız RAM'de ve kişilik/dil/ad değişince, yeniden bağlanınca (`gemini_live` 553, 702–738, 778) **siliniyor**. Kalıcı bellek: `memory.py` (yalnız "bilgi" kayıtları, `memory.json`). | Sebep burada: uygulama her açıldığında/yeniden bağlandığında model **boş sayfayla** başlıyor. |
| **Konum cevaplarının saçmalaması** | `gemini_live._now_block()` (doğrulandı) modele **yalnızca saat/tarih** veriyor; konum **hiç verilmiyor**. Konum yalnız hava paneli (`wx.py` / `panels.weather`) için IP'den tahmin ediliyor (`geo.here`, şehir düzeyi, çoğu zaman yanlış). | Model "neredeyim" sorusunda uyduruyor. Düzeltme: sistem istemine konum bloğu (ayarlardaki KONUM ya da IP tahmini + "yaklaşık" uyarısı). |
| **"Araştır"** | Araç `web_search` → `tools/builtin._web_search` → `brain/web_search.py`: arka planda ayrı bir Gemini oturumu Google'da arar, **yalnızca sesli özet döner, kaynak adresi/URL yok**. Site açma: `actions/win_browser.py` (`browser` aracı). | Kaynakları açmak için aramadan kaynak (URL) bilgisi de alınmalı. |
| **Zamanlayıcı** | Mantık: `timers.py`; panel verisi: `panels.timer_panel`; araçlar: `builtin._timer_set/_timer_cancel/_timer_status/_stopwatch`; bitiş bildirimi: `App._timer_action/_timer_done`; ekran: `hud.js` ~640 (kart) ve ~1344 (büyük "ZAMANLAYICI" görünümü) | Pomodoro buraya bağlanır (mod + mola döngüsü). |
| **Harita** | Veri: `geo.py` (Nominatim, `show_on_map`, `directions`), `panels.map_panel`; ekran: `hud.js` ~563–615 (Leaflet + `tile.openstreetmap.org`) | Çevrimdışıyken çıplak kalır; çevrimdışı katman HUD'a eklenir. |
| **Uygulama kontrolü / izinler** | `actions/win_apps.py` (aç/kapat), `win_uia.py` (başka pencerenin yazı kutularını okuma), `win_shell.py` (PowerShell), `win_media.py`, `win_whatsapp.py`, `win_screen.py`; izin: `win_permissions.py` (yalnız mikrofon/kamera) | Uygulama başına izin sistemi **yok**; eklenecek. |
| **Araç listesi / şemalar** | `tools/schemas.py` (ortak), `win_schemas.py` (Windows metinleri), `tools/builtin.py` (kayıt), `tools/registry.py` | Yeni araç = şema + kayıt. |
| **Kişilikler ve istem** | `personas.py` (`system_instruction`), `prompts/base.md`, `prompts/ultron.md` | Davranış kuralları burada. |
| **Notlar / hafıza / ayarlar** | `notes.py`, `memory.py`, `settings.py`; veri `%APPDATA%\JARVIS V4\` | |
| **Fikir Alanım** | Şimdilik ayrı paket (`JARVIS-Fikir.zip`); yapay zekâya doğrudan taşıma sonraki adım | |

## 3. Bulduğum kök nedenler
1. **Sohbet hatırlamıyor:** geçmiş diske yazılmıyor; Live oturumu kopunca/yeniden başlayınca sıfırdan başlıyor. Çözüm: konuşmaları yerelde sakla, yeni oturumda sistem istemine "son konuşmalar + özet" olarak ver.
2. **Konum saçmalıyor:** modele konum verilmiyor (yukarıda).
3. **"Araştır" tek özet:** arama sonucunda kaynak yok.

## 4. Önerilen sıra (hepsi "yama + HUD", hiçbiri özgün kodu silmez)
1. Konum bloğu + kalıcı konuşma geçmişi (sistem istemi) — küçük, düşük riskli, hemen etkisi büyük.
2. HUD: mikrofon düğmesi taşıma, pomodoro, geliştirilmiş zamanlayıcı, çevrimdışı harita.
3. "Araştır": kaynakları (birden fazla) bulup açma.
4. Uygulama başına izin + uygulama kontrolü (ilk uygulamayı seçince HUD'ını birlikte tasarlarız).
5. Fikir Alanım'ın özelliklerini AI araçlarına taşıma.

## 5. Araçlar (`araclar/`)
- `dogrula.py` — kaynağı özgün bayt koduyla karşılaştırır (`dogrulama.json`).
- `fark.py <modül> <fonksiyon>` — farkı gösterir (hangi satır yanlış decompile edilmiş).
- `indeks.py` — `kaynak/_INDEKS.tsv` üretir.
- `paketle.py`, `insa.py` — PyInstaller arşivini okuyup yamalı exe üretir.
- `pyz_yukle.py` — bir exe'nin içindeki modülleri Linux'ta çalıştırıp test eder.

Not: `JARVIS_DATA_DIR` ortam değişkeni veri klasörünü değiştirir (testlerde kullanıyorum).

## Sürüm 2 eklemeleri (JARVIS-EK-v2)
- `jarvis/ek_bellek.py`: kesinti sarmalayıcısı (`sar`, `gozle`; `GeminiLiveBrain._pump_receive` çalışma anında sarılır), 30 gün saklama (`ek.gecmis_temizle`), önemli bilgi → V4 hafızası `onemli_notlar` (`aktar`).
- `jarvis/ek_spotify.py`: Web API (PKCE, 127.0.0.1:47835), `arac` = `spotify` aracı, işlem günlüğü `ek/spotify-islemler.jsonl`.
- `jarvis/ek_yetenek.py`: SKILL.md deposu `ek/yetenekler/`, GitHub önizleme+onaylı kurulum, `yetenek_oku`/`yetenek_yonet`.
- `jarvis/ek_ozet.py`: `ozetle` (url_context → yerel indirme yedeği, SSRF korumalı), `pano_oku`.
- Testler: `test/test_r2.py` (153), `test/test_pump_gercek.py` (3, özgün bayt kodu), `test/test_hud.py` (53).

## Sürüm 3 (R3) + Yetenek Paketi (R3.1) — özellik → dosya

| Özellik | Dosya / işlev |
|---|---|
| Otomatik odak/çağrı/yazılı mod (odak modu aracı kaldırıldı) | `ek_ses.py` (`beyni_sar`, `_izle`, `MOD_NOTU`), `ek_uyandir.py` ("Hey Bloom" dedektörü; yedek: "Hey Jarvis"; `ek-wake/`) |
| Sahte kırmızı mikrofon rozeti | `ek_ses.py`: `media_status` sarmalayıcı + `mic_calisti` kanıtı + `rozet_onar` |
| Fikir Alanım JARVIS içinde (sade arayüz) | `ek_fikir.py` (sunucu 127.0.0.1:47833, veri, araç, duyuru), `ek_fikir_dosya.py` (üretilen; `araclar/ek_fikir_uret.py`), `fikir_kaynak/` |
| Anımsatıcı = Fikir görevi, takvim = haftalık program | `ek_fikir.agenda_sar()` (`win_agenda` sarmalayıcıları, görev kimliği `fk:<id>`) |
| Ertelenmiş komutlar | `ek_sonra.py` (`arac`, `kontrol`, SMTC yoklaması), `ek.py::_sonra_araci` |
| Yetenek Paketi: vikipedi, sozluk, haberler, eposta_taslagi, guc_islemi, ekran_goruntusu, makro | `ek_paket.py`, kayıt: `ek.py::araclari_kaydet` (`arac_paket`) |
| HUD: POMODORO/SES sekmeleri, FİKİR düğmesi, mod çipi | `hud_ek/jarvis-ek.js/.css` → `ek_hud.py` |
| Testler | `test/test_ek.py`, `test_r2.py`, `test_pump_gercek.py`, `test_r3_ses/fikir/sonra.py`, `test_r31_paket.py`, `test_hud.py` (Playwright), `e2e_fikir.py` |

## Sürüm 3.2 — özellik → dosya
| Özellik | Dosya(lar) | Test |
|---|---|---|
| Ekran görüntüsü (GDI, PIL.ImageGrab yok) | `ek_paket.py` | `test_r31_paket` |
| Canlı döküm | `ek_canli.py`, `ek_bellek.gozle`, `hud_ek/jarvis-ek-akis.css` | `test_r32_canli`, `test_r32_hud` |
| Hava izleyici | `ek_hava.py` | `test_r32_hava` |
| Seçici öğrenme / ders | `ek_ogren.py`, `ek_bellek.aktar`, `ek.py` (ilkeler, `ders_*`) | `test_r32_ogren` |
| Gemini model yedekleme | `ek_model.py` | `test_r32_model` |
| Konsey | `ek_konsey.py`, `ek.py` (`konsey` aracı, `ek_konsey` HUD mesajı), `hud_ek/jarvis-ek.js` KONSEY sekmesi | `test_r32_konsey`, `test_r32_panel` |
| Ayrıntılı araştırma → not | `ek.py` (`_arastir_ayrintili`), `ek_fikir.py` (`not_yaz`, `parcala`) | `test_r32_arastir`, `test_r3_fikir` |
| Yetenek GitHub (ağaç + raw + ZIP yedeği) | `ek_yetenek.py` (`_agac*`, `_topla`) | `test_r2` |
| Fikir kayıt: 3'lü birleştirme, kilit dayanıklılığı | `ek_fikir.py` (`birlestir`, `snapshot_*`), `fikir_kaynak/jarvis-store.js` | `test_r3_fikir`, `e2e_fikir` |

## Sürüm 3.2.1
| Özellik | Dosya |
|---|---|
| Sohbet eski görünümüne döndü; canlı satır tek metin düğümü + rAF pompası (akıcı), `ek-sabit` ile titremesiz geçiş | `hud_ek/jarvis-ek-akis.css`, `hud_ek/jarvis-ek.js` (`canliYaz`, `pump`, `kalici`) |

## Sürüm 3.2.2
Üst çubuk düğmesi "POMODORO" -> "EK PANELİ"; panel başlığında sürüm. Sekmeler: hud_ek/jarvis-ek.js `TABS`.

## Sürüm 3.3
| Özellik | Dosya |
|---|---|
| Uygulama içi adlar sadeleşti (PANEL / JARVIS) | `hud_ek/jarvis-ek.js` |
| KONSEY › MODEL EKLE (OpenRouter :free metin modeli; `konsey_ekstra`, id `x-N`) | `kaynak/jarvis/ek_konsey.py` (`model_ekle`, `model_sil`, `slug_coz`), `ek.py` (`ek_konsey` köprüsü), `test/test_r33_model.py` |

## Sürüm 3.3.1
Konsey aracı 22 sn bekler, sürerse arka planda biter ve `ek._announce` ile duyurulur (`ek_konsey.arac_konsey`, `KONSEY_BEKLE`); `_paralel` zaman aşımında beklemez. Test: `test/test_r33_konsey_arka.py`.

## Sürüm 3.4
| Özellik | Dosya | Test |
|---|---|---|
| Derin araştırma: plan → paralel kaynaklı aramalar → sentez (`standart`: 3 alt soru; `ayrintili`: 6 alt soru + boşluk denetimi, ≤2 ek arama); rapor HUD kartında, "kaydet" denince Fikir'e; `hizli=true` eski tek çağrı | `kaynak/jarvis/ek_arastir.py`, `ek.py` (`_arastir_boru`, `_grounded(bulgu)`, `_uret_metin`, `SON_RAPOR`, `arastir`), `hud_ek/jarvis-ek.js` (`showSources` özet) | `test_r32_arastir` (29), `test_ek` |
| Fikir Alanım yetkinliği: 30+ yeni `fikir` işlemi (not düzenle/sil/etiketle/sabitle/bağla/benzer/geliştir/göreve çevir, toplu görev, geciken, hafta oku/düzenle/sil, boş zaman, planla/plan_uygula, rutin, günlük, kaynak, kategori, gözden geçir) | `kaynak/jarvis/ek_fikir_arac.py` (`calistir`, `ISLEMLER`), `ek_fikir.arac` (devir), `ek_fikir.istem_blogu`, `ek.py` (`fikir` şeması, `YETENEK_NOTU`) | `test_r34_fikir` (100), `e2e_r34_fikir` (+ `e2e_fikir_arac_sunucu.py`) |
Kurallar: yazma yalnızca `ek_fikir.duzenle` ile; silme → geri dönüşüm kutusu, metin değişimi → eski sürüm kutuda; gizli kategori hiç görünmez; `fikir_gelistir` 20 sn sonra arka plana geçer ve `_announce` eder.

## Sürüm 3.5
| Özellik | Dosya | Test |
|---|---|---|
| Çoklu görev iş yöneticisi: en çok 3 eşzamanlı iş, durum/iptal/devam, yeniden başlatmada `yarim`, kayıpsız teslim kuyruğu (`teslim_et`) | `kaynak/jarvis/ek_isler.py`, `ek.py` (`isler` aracı, istem bloğu) | `test_r35_isler` (52) |
| Limit dayanıklı araştırma: 429 → bekle + yeniden dene, günlük kota → `yarim`, alt soru başına kontrol noktası, otomatik devam (180 sn, ≤3) | `ek_arastir.py` (`_dene`, `hata_turu`, `bekleme_suresi`, `Yarim`, `Iptal`), `ek_model.uret`, `ek.py` (`_arastir_boru`, `_arastirma_devam`) | `test_r32_arastir` (29), `test_r35_isler` |
| Şema (diyagram) bölgesi: Fikirler panosunda SVG resimli not (kategori "Şemalar", etiket `şema`); düzenlenebilir kaynak `fikir.sema.v1` | `ek_sema.py` (motor: akis/agac/zihin/zaman), `ek_fikir_arac.py` (`sema_ekle/guncelle/oku`), `ek.py` (`fikir` şeması) | `test_r35_sema_kod`, `e2e_r34_fikir` |
| Kod yazma + Visual Studio Code: güvenli yol, yedek, sözdizimi denetimi, VS Code bulma/açma, `duzenle`, onaylı `calistir`, arka plan `proje` hattı (plan → dosya → denetim/onarım → VS Code → bildir) | `ek_kod.py`, `ek.py` (`kod` aracı, `_kod_istem`) | `test_r35_sema_kod` (108) |

## Sürüm 3.6
| Özellik | Dosya | Test |
|---|---|---|
| Şema defterde: not açılınca metin + şema yan yana (varsayılan) ya da şema metnin üstünde (düğmeyle değişir, `fikir.sema.layout` kalıcı); kartta şema küçük ve kırpılmadan (`.note-img.schema`); şema notu orta boy | `fikir_kaynak/` (`index.html` `#notebookBody/#notebookSchema`, `app.js` `renderNotebookSchema`/`isSchemaImage`, `theme-fix.css` sonu), `ek_fikir_arac.py` (`_sema_yer`) → `araclar/ek_fikir_uret.py` | `e2e_r34_fikir` |
| MCP geçidi + REA: tek `mcp` aracı (sunucular/kur_rea/ekle/sil/ara/sema/cagir/kapat); stdio JSON-RPC istemcisi, sayfalı `tools/list`, arama, risk sınıfı (okuma/orta/yüksek), uzun çağrı = arka plan işi, tam çıktı `ek/mcp-cikti/`; REA hazır ayarı `npx -y rea-agents@6.8.0 mcp` (Node 22.23.4+/24.22.1+/26.12.1+ denetimi) | `kaynak/jarvis/ek_mcp.py`, `ek.py` (`mcp` aracı) | `test_r36_mcp`, `test/fake_mcp.py` |
| Hazır yetenekler (özgün): sistematik-hata-ayiklama, once-planla, bitirmeden-dogrula, derin-dusun-karar, cerrahi-degisiklik, rea-tersine-muhendislik (ilk çalıştırmada bir kez yazılır) + `yetenek_yonet(oneriler)` GitHub önerileri | `ek_yetenek_tohum.py`, `ek_yetenek.py` (`_tohum_bir_kez`) | `test_r36_yetenek` |
| İş teşhisi: `isler(durum)` gerçek ayrıntı (son model, son 12 olay, sessizlik süresi); `_dene` vazgeçme/bekleme nedenini yazar | `ek_isler.py` (`olay`, `_teshis`), `ek_model.py` (`son_model`), `ek_arastir.py` (`_dene`) | `test_r36_mcp` |

## Sürüm 3.7
| Özellik | Dosya | Test |
|---|---|---|
| Ekran oturumu: `ekran` aracı (iste/durum/bak/tahta/hamle/tikla/surukle/kaydir/yaz/tus/kapat). İzni yalnızca kullanıcı HUD kartından verir (SADECE BAK / KONTROL VER / REDDET); 1–60 dk süre, ESC acil durdurma, en çok 300 eylem, eylemler arası ≥0.35 sn; JARVIS'in kendi penceresine, şifre/giriş/ödeme başlıklı pencerelere tıklama-yazma ve Win/Alt+F4 vb. tuşlar engelli. Tüm ekran GDI ile yakalanır, görüntü modele 0-1000 koordinatıyla döner. Siteye özel mantık yok | `kaynak/jarvis/ek_ekran.py` (`WinAPI` ctypes + değiştirilebilir `API`), `ek.py` (araç, `durum()['ekran']`, köprü `ek_ekran`), `hud_ek/jarvis-ek.js/.css` (`#ek-ekran`) | `test/test_r37_ekran.py` (75), `test/test_r37_hud.py` (13) |

## Sürüm 3.7.1
| Özellik | Dosya | Test |
|---|---|---|
| JARVIS'in kendi penceresi: `ekran(pencere=jarvis)` ile bak/tikla/surukle/kaydir/yaz/tus; PrintWindow, boşsa öne alıp kırp; izin kartı beklerken ve JARVIS girdi gönderdikten 3 sn içinde kart onayı REDDEDİLİR (kendi kendine izin engeli) | `ek_ekran.py` (`WinAPI.kendi*`, `_kendi_hazir`, `SENTETIK_BEKLE`) | `test_r37_ekran.py` |
| Görev çubuğu yerine pencere listesi: `ekran(pencereler)` (görüntüsüz, hızlı) ve `ekran(ac, uygulama)` (küçültülmüşse geri getirir) | `ek_ekran.py` (`WinAPI.pencereler/one_getir`) | idem |
| Spotify kök neden: `spotify_installed()` Mağaza klasörünü okuyamayınca "yüklü görünmüyor" → sessizce tarayıcıda YouTube. Artık `spotify:` protokol kaydı / çalışan süreç de "kurulu" sayılır; komut aracı yoksa talimat: izin iste → ac → bak → çift tıkla. `play_spotify` süresi günlüğe `ek_sure:` | `ek_ekran.win_yamalari()` (çalışma anında sarar; `ek.araclari_kaydet` çağırır) | idem |
| `analyze_screen` yalnızca önde pencere: sonuca "görev çubuğu/JARVIS için ekran aracı" notu, tam ekran isteği yönlendirir; süre günlüğe | idem | idem |

## Sürüm 3.8.0 — satranç kaldırıldı, anlama programı, Fikir Alanım birleşimi
| Özellik | Dosya | Test |
|---|---|---|
| Satranç tümüyle kaldırıldı: `satranc` aracı, `ek_satranc/ek_motor/ek_tahta/ek_oyun`, `satranc-ekran` yeteneği (eski tohum açılışta silinir: `KALDIR`). `degisim_orani` `ek_ekran`a taşındı | `ek_ekran.py`, `ek_yetenek_tohum.py`, `ek.py` | `test_r37_ekran.py`, `test_r36_yetenek.py` |
| Anlama programı: `anla` aracı (coz / sozluk_ekle / sozluk_sil / sozluk_liste / gunluk / sinama). Sözlük (≤40 terim, istemde ≤600 karakter), ikinci yorum (Gemini → konsey sağlayıcısı → yerel kural), belirsizlik denetimi, yanlış anlama günlüğü (`ek_bellek.aktar` düzeltmeleri yazar), 63 cümlelik ayarlı + 26 cümlelik tutulmuş sınama | `ek_anla.py`, `ek.py`, `ek_bellek.py` | `test_r38_anla.py` |
| Hazır yetenek `gorev-rutin-plani` (özgün) | `ek_yetenek_tohum.py` | `test_r36_yetenek.py` |
| Fikir Alanım: Görevler+Rutin tek sekme (`#routinePanel` `#view-tasks` içinde), küçük sekmeler (`compact.css`), `go('routine')` görev sekmesine yönlenir | `fikir_kaynak/index.html`, `app.js`, `compact.css`, `ek_fikir_dosya.py` (üretilir: `araclar/ek_fikir_uret.py`) | `e2e_fikir.py`, `e2e_r34_fikir.py` |

## Sürüm 3.9.0 — Hermes Agent köprüsü
| Özellik | Dosya | Test |
|---|---|---|
| `hermes` aracı: durum / kurulum / ayarla / gonder / sonuc / durdur / onay / yetenek_listele / yetenek_al. Hermes API sunucusu (`/v1/runs`, `/v1/capabilities`, `/approval`, `/stop`) üzerinden iş devri; `ek_isler` arka plan işi + `DEVAM['hermes']`; anahtar Hermes `.env`'den; onay yalnızca kullanıcı sözüyle | `ek_hermes.py`, `ek.py` | `test_r38_hermes.py` (sahte Hermes sunucusu) |
| Hermes yeteneklerini önizleme+onayla JARVIS'e alma (yalnızca SKILL.md + references; scripts alınmaz) | `ek_hermes.py` (`ek_yetenek` ayrıştırıcı/risk taraması) | `test_r38_hermes.py` |

| Fikir Alanım › Görev & Rutin › StudyTracker düğmesi (rutin listesinin altı). Gömülüyken `postMessage {fikir:"ac"}` → HUD → `ek_ac` (yalnız `SABIT_ADRESLER`) → `ek_ekran.site_ac`: tarayıcı penceresi başlığında "studytracker" varsa öne alır, yoksa yeni sekme. Tek başına: `window.open(url,"studytracker")` | `fikir_kaynak/studytracker.js`, `hud_ek/jarvis-ek.js`, `ek.py`, `ek_ekran.py` (`site_ac`, `site_pencere_sec`) | `test_r39_site.py` (19), `e2e_r39_studytracker.py` (11) |
| Kişisel kullanım: Hakkında/yapan/takip/yeni sürüm kaldırıldı (`about.py` boş içerik, `updates.enabled()=False`, `App._follow_due/on_creator` etkisiz, `show_creator` aracı kayıttan çıkarıldı; HUD'da CSS gizleme + `Follow/Info/Update` etkisiz + `showTab("hakkinda")→genel`) | `kaynak/jarvis/about.py`, `updates.py`, `app.py`, `tools/builtin.py`, `hud_ek/jarvis-ek.css`, `hud_ek/jarvis-ek.js` | `test_r39_kisisel.py` (17), `test_r39_kisisel_hud.py` (14) |


## 3.10.0 — eklenenler (bloom)
| Konu | Yer |
|---|---|
| Ad değişimi (JARVIS → BLOOM) | `brand.custom/window_title` yaması; `hud_ek/jarvis-ek.js` içinde MutationObserver metin çevirici (`adCevir`); `ek_*` metinleri. Veri klasörü `%APPDATA%\JARVIS V4` (`paths.APP_NAME`) ve `WIN_APP_ID` BİLEREK aynı kaldı. |
| ULTRON hikâye modu kapalı | `story.enabled/state/_save` yaması, açılışta `story_enabled=False`, `jarvis-ek.css` ile ★ ve ayar satırı gizli. Persona, `chains.py`, `awakening.py` duruyor. |
| Yayın modu | `ek_yayin.py` (sahte konum/hava/kişiler/bellek/fikir/kimlik; ekran + sesli çıktı). Test: `test_r310_yayin`, `test_r310_hud`. |
| Kendini geliştirme | `ek_gelisim.py` (araç `gelisim`: kaydet/liste/hermese_ver). Programın kendi dosyalarını DEĞİŞTİRMEZ; yetenek (SKILL.md) yolu. Test: `test_r310_gelisim`. |
| "Hey Bloom" modeli | `araclar/uyandir_egit.py` (sentetik Piper sesiyle eğitim; akış ızgarasına birebir uyumlu gömme), `araclar/uyandir_dogrula.py` (gerçek `Dedektor.besle` ile sınama), `ek_wake/models/hey_bloom_v0.1.onnx`. `ek_uyandir.Dedektor`: Hey Bloom için son 6 adımın en az 3'ü eşiği geçmeli. |
| Kendi koduna izinli erişim | `ek_kendi.py` (araç `kendi_kod`): salt okunur; kaynak klasörü `bloom-kaynak/` (exe'nin yanında) + HUD dosyaları + günlük; `hatalar` günlüğü kaynakla eşleştirir; `yama_oner` yalnızca öneri dosyası yazar. HUD: YETENEKLER sekmesi altında izin anahtarı. Paket: `araclar/kaynak_paketi.py`. Test: `test_r310_kendi` (70), `test_r310_hud`. |

## 3.11.1 — Aşama 2 (sadeleştirme)
| Ne | Nerede | Test |
|---|---|---|
| PANEL 3 sekme (`GRUPLAR`: odak/arac/gelismis; paneller `data-pane`, `showTab(panel)` grubu açar ve panele kaydırır; `ekPanelAc('ses')` vb. aynen çalışır) | `hud_ek/jarvis-ek.js` (`GRUPLAR`, `BASLIK`, `GRUP`), `jarvis-ek.css` (`.ek-grup`) | `test_hud`, `test_r310_hud`, `test_r32_panel` |
| Temiz HUD üretimi: özgün yazarın `[hikaye]…[/hikaye]` ve `[-hikaye]` işaretlerini ayıklar | `araclar/hud_temizle.py` → `hud_temiz/`; HUD testleri temiz kopyayla: `araclar/hud_temiz_test.sh <test…>` | HUD testleri temiz kopyayla da geçer |
| Temiz HUD'u kullanıcıya uygulama | zip içinde `BLOOM-EK/hud-temiz/UYGULA.ps1` (SHA doğrular, .yedek alır, -Geri) | PowerShell betiği çalıştırılmadı (sandbox'ta pwsh yok) |


## 3.12.0 — Mark 2 web ekranı (jarvis-main arayüzü)
- `web_hud/` — React/Vite kaynağı (jarvis-main'den); `src/bloom/` BLOOM'a özgü parçalar. Derle: `cd web_hud && npx vite build`; sonra `python3 araclar/ek_web_uret.py` (dist → `ek_web_dosya.py`, MediaPipe hariç).
- `kaynak/jarvis/ek_web.py` — yerel HTTP hizmeti (Host/Origin denetimli): arayüz dosyaları, `/api/dashboard`, kitaplık, el varlıkları (`el-varliklari/`).
- `kaynak/jarvis/ek_pano.py` — hava (Open-Meteo), döviz (TCMB), haber (TRT/BBC RSS); kaynak çökerse yalnız o alan boş, veri uydurulmaz.
- `hud_ek/bloom-web.js` — HUD sayfasında iframe + postMessage köprüsü (Ctrl+Shift+W aç/kapat).
- Testler: `test/test_r312_web.py` (Python, exe ile), `test/test_r312_hud.py` (Playwright; `_web_sunucu.py` yardımcı).

- `kaynak/jarvis/ek_surum.py` — sürüm sabiti (`SURUM`), `--version/--help/--log` komutları, araç listesi (registry'den), günlük maskeleme. LOG paneli: `web_hud/src/bloom/LogPanel.tsx`. Testler: `test/test_r312_surum.py`.
