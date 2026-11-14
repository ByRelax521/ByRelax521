/* BLOOM EK — HUD eklentisi: POMODORO / SES / SPOTIFY / YETENEK / BELLEK paneli, Fikir Alanım katmanı, ses modu çipi, araştırma kaynak kartı, çevrimdışı harita yedeği.
   hud.js'e dokunmaz; hud.js'ten sonra yüklenir, window.jarvis'e kendi işlevlerini ekler.
   Python ile konuşma: send("ek_*") → jarvis/ek.py ; Python → window.jarvis.ekDurum / ekKaynaklar / ekAlarm. */
(function(){
"use strict";
if(window.__ekYuklu) return;
window.__ekYuklu = true;

const $id = id => document.getElementById(id);
function h(tag, cls, text){ const e = document.createElement(tag); if(cls) e.className = cls; if(text != null) e.textContent = text; return e; }
function post(kind, data){ try{ if(typeof send === "function") return send(kind, data); }catch(e){} }
function pad(n){ return String(n).padStart(2, "0"); }
function mmss(sec){ sec = Math.max(0, Math.round(sec)); return pad(Math.floor(sec / 60)) + ":" + pad(sec % 60); }

let D = null;            // Python'dan son durum (ekDurum)
let tick = 0;            // saniyelik sayaç (yalnızca pomodoro çalışırken)
let built = false;
const R = {};            // panel öğeleri

/* ---------------- bloom: HUD'daki eski "JARVIS" yazılarını BLOOM'a çevirir ----------------
   HUD dosyaları kullanıcının diskinde ve değişmez; görünen metin burada, sayfa yüklenince ve değiştikçe yeniden yazılır.
   Yalnızca görünen metin ve title/placeholder/aria-label/alt öznitelikleri; girdi kutularına, kimliklere ve koda dokunmaz.
   Türkçe ek uyumu: JARVIS'in → BLOOM'un, JARVIS'e → BLOOM'a, JARVIS'te → BLOOM'da. "JARVIS V4" (veri klasörü adı) olduğu gibi kalır. */
const ADLAR_RE = /(?<![\w.])(JARVIS|Jarvis)(?!\w)(?!-Kod)(?!\.exe)(?!\s*V4)(?:(['’])([^\W\d_]+))?/g;
function adUyum(s){ let o = ""; for(const c of s) o += (c === "e" ? "a" : (c === "ı" || c === "i" || c === "ü") ? "u" : c); return o[0] === "t" ? "d" + o.slice(1) : o; }
function adCevir(s){
  if(typeof s !== "string" || (s.indexOf("JARVIS") < 0 && s.indexOf("Jarvis") < 0)) return s;
  return s.replace(ADLAR_RE, (m, ad, ap, ek) => (ad === "JARVIS" ? "BLOOM" : "Bloom") + (ap ? ap + adUyum(ek) : ""));
}
const AD_OZNITELIK = ["title", "placeholder", "aria-label", "alt"];
function adDugum(n){
  if(!n) return;
  if(n.nodeType === 3){ const p = n.parentNode; if(p && /^(SCRIPT|STYLE|TEXTAREA|INPUT)$/.test(p.nodeName)) return; const v = adCevir(n.nodeValue); if(v !== n.nodeValue) n.nodeValue = v; return; }
  if(n.nodeType !== 1 || /^(SCRIPT|STYLE|IFRAME|CANVAS)$/.test(n.nodeName)) return;
  for(const a of AD_OZNITELIK){ if(n.hasAttribute && n.hasAttribute(a)){ const v = adCevir(n.getAttribute(a)); if(v !== n.getAttribute(a)) n.setAttribute(a, v); } }
  for(let c = n.firstChild; c; c = c.nextSibling) adDugum(c);
}
function adBaslat(){
  try{
    if(document.title) document.title = adCevir(document.title);
    adDugum(document.body || document.documentElement);
    new MutationObserver(list => {
      for(const m of list){
        if(m.type === "characterData") adDugum(m.target);
        else if(m.type === "attributes"){ const v = adCevir(m.target.getAttribute(m.attributeName)); if(v !== m.target.getAttribute(m.attributeName)) m.target.setAttribute(m.attributeName, v); }
        else for(const n of m.addedNodes) adDugum(n);
      }
      if(/JARVIS|Jarvis/.test(document.title)) document.title = adCevir(document.title);
    }).observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: AD_OZNITELIK});
  }catch(e){}
}
adBaslat();
window.__adCevir = adCevir;

/* ---------------- üst çubuk düğmesi ---------------- */
const btn = h("button", "ctl ek-ctl");
btn.id = "t-ek"; btn.type = "button"; btn.title = "BLOOM paneli: pomodoro, ses, Spotify, yetenekler, konsey, bellek";
btn.dataset.ek = "off";
btn.innerHTML = '<i class="dot"></i><span class="ek-lbl">PANEL</span> <b id="t-ek-state"></b>';
{
  const anchor = $id("t-persona");
  const bar = $id("topbar");
  if(anchor && anchor.parentNode) anchor.parentNode.insertBefore(btn, anchor);
  else if(bar) bar.appendChild(btn);
}
const stateEl = btn.querySelector("#t-ek-state");
btn.addEventListener("click", () => openPanel());

/* ---------------- panel ---------------- */
function row(title, small){
  const r = h("div", "row2");
  const d = h("div"); d.append(document.createTextNode(title));
  if(small != null){ const s = h("small", null, small); d.appendChild(s); r.small = s; }
  r.appendChild(d); r.label = d;
  return r;
}
function sw(){ const b = h("button", "switch"); b.type = "button"; b.setAttribute("role", "switch"); b.setAttribute("aria-checked", "false"); return b; }
function num(label, value, min, max){
  const w = h("label", "ek-num"); const i = h("input"); i.type = "number"; i.min = min; i.max = max; i.value = value;
  w.append(h("span", null, label), i); w.input = i; return w;
}

const P = {};            // paneller: odak / ses / spotify / yetenek / konsey / bellek / yayin
// Sadeleşme (3.11.1): 7 sekme yerine 3 sekme; paneller (ve ekPanelAc/çip adları) aynı kaldı, yalnız gruplanıp alt alta gösterilir.
const GRUPLAR = [["odak", "ODAK", ["odak", "ses", "spotify"]],
                 ["arac", "ARAÇLAR & YETENEKLER", ["yetenek", "konsey"]],
                 ["gelismis", "GELİŞMİŞ", ["bellek", "yayin"]]];
const BASLIK = {ses: "SES", spotify: "SPOTIFY", yetenek: "YETENEKLER · MCP · KENDİ KODU", konsey: "KONSEY", bellek: "BELLEK", yayin: "YAYIN MODU"};
const TABS = GRUPLAR.reduce((a, g) => a.concat(g[2].map(k => [k, g[1]])), []);   // [pane, grup etiketi]
const GRUP = {}; for(const [gk, , panes] of GRUPLAR) for(const k of panes) GRUP[k] = gk;
function showTab(name){
  if(!P[name]) name = "odak";
  const g = GRUP[name];
  for(const [k] of TABS) P[k].classList.toggle("on", GRUP[k] === g);
  for(const [gk] of GRUPLAR) R.tabs[gk].setAttribute("aria-selected", String(gk === g));
  R.tab = name;
  const ilk = GRUPLAR.find(x => x[0] === g)[2][0];
  if(name !== ilk){ try { P[name].scrollIntoView({block: "start"}); } catch(e){} }
}
function btnX(label, cls, fn){ const b = h("button", cls || "btn", label); b.type = "button"; if(fn) b.addEventListener("click", fn); return b; }
function sonuc(el, msg, bad){ el.textContent = msg || ""; el.className = "note " + (bad ? "bad" : "good"); }
function guvenli(p, fn){ Promise.resolve(p).then(fn).catch(() => {}); }

function build(){
  if(built) return; built = true;
  const ov = h("div", "overlay"); ov.id = "ov-ek";
  const sheet = h("div", "sheet eksheet"); ov.appendChild(sheet);
  const close = h("button", "close", "✕"); close.type = "button"; close.title = "Kapat (Esc)"; close.setAttribute("aria-label", "Kapat");
  close.addEventListener("click", () => { if(typeof closeOverlays === "function") closeOverlays(); else ov.classList.remove("on"); });
  sheet.append(close, h("h2", null, "BLOOM"));
  R.tabs = {};
  const bar = h("div", "ek-tabs");
  for(const [gk, label, panes] of GRUPLAR){
    const t = h("button", "ek-tab", label); t.type = "button"; t.setAttribute("aria-selected", "false");
    t.addEventListener("click", () => showTab(panes[0])); R.tabs[gk] = t; bar.appendChild(t);
  }
  for(const [k] of TABS){
    P[k] = h("div", "ek-pane" + (GRUPLAR.some(x => x[2][0] === k) ? " ek-ilk" : "")); P[k].dataset.pane = k;
    if(BASLIK[k]) P[k].appendChild(h("h3", "ek-grup", BASLIK[k]));
  }
  sheet.appendChild(bar);
  for(const [k] of TABS) sheet.appendChild(P[k]);
  buildOdak(P.odak);
  buildSes(P.ses);
  buildSpotify(P.spotify);
  buildYetenek(P.yetenek);
  buildKonsey(P.konsey);
  buildBellek(P.bellek);
  buildYayin(P.yayin);
  showTab("odak");
  document.body.appendChild(ov);
  R.ov = ov;
}

function buildOdak(sheet){
  sheet.appendChild(h("p", "lead", "Pomodoro odak ve mola evrelerini kendisi yönetir; odak evresinde BLOOM kendiliğinden konuşmaz. Dinleme artık otomatik: BLOOM penceresi öndeyse serbest, değilse \"Hey Bloom\" ile (aşağıdaki SES bölümü)."));

  // pomodoro: sayaç
  const pomo = h("div", "ek-pomo"); R.pomo = pomo;
  R.phase = h("div", "ek-phase", "HAZIR"); R.big = h("div", "ek-big", "25:00");
  R.task = h("div", "ek-task"); R.bar = h("div", "ek-bar"); R.fill = h("i"); R.bar.appendChild(R.fill);
  pomo.append(R.phase, R.big, R.bar, R.task);
  sheet.appendChild(pomo);

  // pomodoro: kurulum
  const setup = h("div", "ek-setup"); R.setup = setup;
  const task = h("input", "ek-in"); task.type = "text"; task.maxLength = 60; task.placeholder = "Ne üzerinde çalışacaksın? (isteğe bağlı)";
  task.autocomplete = "off"; task.spellcheck = false; R.taskIn = task;
  const nums = h("div", "ek-nums");
  R.nWork = num("ODAK dk", 25, 1, 120); R.nShort = num("MOLA dk", 5, 1, 30);
  R.nLong = num("UZUN MOLA dk", 15, 1, 60); R.nRounds = num("TUR", 4, 1, 8);
  nums.append(R.nWork, R.nShort, R.nLong, R.nRounds);
  const start = h("button", "btn", "POMODORO BAŞLAT"); start.type = "button";
  start.addEventListener("click", () => post("ek_pomo", {eylem: "baslat", gorev: task.value.trim(),
    calisma: +R.nWork.input.value, kisa: +R.nShort.input.value, uzun: +R.nLong.input.value, tur: +R.nRounds.input.value}));
  setup.append(task, nums, start);
  sheet.appendChild(setup);

  // pomodoro: kumanda
  const ctl = h("div", "ek-ctl-row"); R.ctl = ctl;
  R.bPause = h("button", "btn ghost", "DURAKLAT"); R.bSkip = h("button", "btn ghost", "EVREYİ ATLA"); R.bStop = h("button", "btn danger", "DURDUR");
  for(const b of [R.bPause, R.bSkip, R.bStop]) b.type = "button";
  R.bPause.addEventListener("click", () => post("ek_pomo", {eylem: D && D.pomo && D.pomo.duraklat ? "devam" : "duraklat"}));
  R.bSkip.addEventListener("click", () => post("ek_pomo", {eylem: "atla"}));
  R.bStop.addEventListener("click", () => post("ek_pomo", {eylem: "durdur"}));
  ctl.append(R.bPause, R.bSkip, R.bStop);
  sheet.appendChild(ctl);
  R.today = h("p", "note", ""); sheet.appendChild(R.today);

  // anahtarlar
  const rPerf = row("PERFORMANS MODU", "Görüntü kalitesini düşürür: ışımalar ve kare sayısı azalır, bilgisayarı daha az yorar.");
  R.swPerf = sw(); rPerf.appendChild(R.swPerf);
  R.swPerf.addEventListener("click", () => {
    const low = typeof SETTINGS === "object" && SETTINGS && SETTINGS.render_quality === "low";
    const q = low ? "high" : "low";
    try{
      SETTINGS.render_quality = q;
      if(typeof fillSettings === "function") fillSettings();
      if(typeof syncQuality === "function") syncQuality();
    }catch(e){}
    post("settings", {changes: {render_quality: q}});
    paint();
  });
  sheet.append(rPerf);
  R.sonraBaslik = h("p", "lead ek-sonra-b", "ERTELENMİŞ KOMUTLAR"); R.sonraListe = h("div", "ek-sonra");
  sheet.append(R.sonraBaslik, R.sonraListe);
  R.foot = h("p", "note", ""); sheet.appendChild(R.foot);
}

/* ---------------- SPOTIFY ---------------- */
function buildSpotify(p){
  p.appendChild(h("p", "lead", "Spotify'ı açmak, çalmak ve durdurmak zaten kurulumsuz çalışır. Çalma listelerine şarkı eklemek/çıkarmak için Spotify'ın resmi arayüzüne bir kez bağlanman gerekir. BLOOM listelerini yalnızca sen isteyince değiştirir; yaptığı her değişiklik aşağıda yazılır ve \"geri al\" diyebilirsin."));
  R.spStat = h("div", "ek-stat", "—"); p.appendChild(R.spStat);
  const steps = h("ol", "ek-steps");
  const li1 = h("li"); li1.append("developer.spotify.com/dashboard sayfasında bir uygulama oluştur (Spotify Premium hesabı gerekir). ");
  const open = btnX("SAYFAYI AÇ", "ek-mini", () => post("ek_ac", {url: "https://developer.spotify.com/dashboard"})); li1.appendChild(open);
  const li2 = h("li"); li2.append("Redirect URI kutusuna şunu yaz: ");
  R.spUri = h("code", "ek-code", "http://127.0.0.1:47835/callback"); li2.appendChild(R.spUri);
  li2.appendChild(btnX("KOPYALA", "ek-mini", () => post("copy", {text: R.spUri.textContent})));
  const li3 = h("li", null, "\"Web API\" kutusunu işaretle, kaydet. Uygulamanın Client ID'sini kopyala ve aşağı yapıştır.");
  steps.append(li1, li2, li3); p.appendChild(steps);
  R.spId = h("input", "ek-in"); R.spId.type = "text"; R.spId.placeholder = "Client ID (32 karakter)"; R.spId.autocomplete = "off"; R.spId.spellcheck = false;
  p.appendChild(R.spId);
  const rowb = h("div", "ek-ctl-row");
  R.spBaglan = btnX("KAYDET VE BAĞLAN", "btn", () => {
    const v = R.spId.value.trim();
    const go = () => guvenli(post("ek_spotify", {eylem: "baglan"}), m => sonuc(R.spMsg, m, /^Hata/.test(m || "")));
    if(v){ guvenli(post("ek_spotify", {eylem: "kaydet", client_id: v}), m => { if(/^Hata/.test(m || "")) sonuc(R.spMsg, m, true); else go(); }); }
    else go();
  });
  R.spKes = btnX("BAĞLANTIYI KALDIR", "btn ghost", () => guvenli(post("ek_spotify", {eylem: "kes"}), m => sonuc(R.spMsg, m)));
  rowb.append(R.spBaglan, R.spKes); p.appendChild(rowb);
  R.spMsg = h("p", "note"); p.appendChild(R.spMsg);
  p.appendChild(h("div", "ek-sec", "SON İŞLEMLER"));
  R.spLog = h("div", "ek-log"); p.appendChild(R.spLog);
  p.appendChild(h("p", "note", "Not: Spotify'ın 2026 kuralları gereği bu bağlantı yalnızca Premium hesapla çalışır. Şifren BLOOM'a verilmez; izin Spotify'ın kendi sayfasında verilir ve istediğin an buradan kaldırılır."));
}

const EYLEM_AD = {ekle: "EKLENDİ", cikar: "ÇIKARILDI", olustur: "LİSTE OLUŞTURULDU", begen: "BEĞENİLDİ", begeniyi_kaldir: "BEĞENİ KALDIRILDI",
  geri_alindi: "GERİ ALINDI", geri_alindi_ekle: "EKLEME GERİ ALINDI", geri_alindi_cikar: "ÇIKARMA GERİ ALINDI"};
function paintSpotify(){
  const s = (D && D.spotify) || {};
  let t = "BAĞLI DEĞİL", cls = "off";
  if(s.login === "bekliyor"){ t = "BAĞLANIYOR · tarayıcıda Spotify iznini onayla"; cls = "wait"; }
  else if(s.bagli){ t = "BAĞLI" + (s.hesap ? " · " + s.hesap : "") + (s.premium === false ? " · PREMIUM GÖRÜNMÜYOR" : ""); cls = "on"; }
  else if(s.login === "hata"){ t = "BAĞLANAMADI · " + (s.mesaj || ""); cls = "bad"; }
  R.spStat.textContent = t; R.spStat.dataset.s = cls;
  if(s.redirect) R.spUri.textContent = s.redirect;
  R.spKes.hidden = !s.bagli;
  R.spBaglan.textContent = s.bagli ? "YENİDEN BAĞLAN" : "KAYDET VE BAĞLAN";
  R.spBaglan.disabled = s.login === "bekliyor";
  if(s.client_id && !R.spId.value) R.spId.placeholder = "Client ID kayıtlı (değiştirmek için yapıştır)";
  R.spLog.replaceChildren();
  const ops = (s.islemler || []).slice().reverse();
  if(!ops.length) R.spLog.appendChild(h("div", "ek-empty", "Henüz bir işlem yok."));
  for(const o of ops){
    const d = h("div", "ek-op");
    const dt = new Date((o.t || 0) * 1000);
    d.append(h("b", null, EYLEM_AD[o.eylem] || String(o.eylem).toUpperCase()), h("span", null, (o.liste ? o.liste + " · " : "") + (o.parcalar || []).join("; ")),
      h("small", null, pad(dt.getHours()) + ":" + pad(dt.getMinutes())));
    R.spLog.appendChild(d);
  }
}

/* ---------------- YETENEKLER ---------------- */
function buildYetenek(p){
  p.appendChild(h("p", "lead", "Yetenek, BLOOM'a \"şu işi şöyle yap\" diyen bir talimat dosyasıdır (Agent Skills biçimi: içinde SKILL.md olan klasör). Kendin yazdırabilir ya da GitHub'dan kurabilirsin. Betik (scripts) çalıştırılmaz; yalnızca talimat okunur. Yeni bir AI MODELİ eklemek istiyorsan burası değil, aşağıdaki KONSEY bölümündeki MODEL EKLE kutusu."));
  R.ysList = h("div", "ek-ylist"); p.appendChild(R.ysList);
  p.appendChild(h("div", "ek-sec", "GITHUB'DAN KUR"));
  R.ysUrl = h("input", "ek-in"); R.ysUrl.type = "text"; R.ysUrl.placeholder = "https://github.com/kullanici/depo  (ya da .../tree/main/skills/ad)";
  R.ysUrl.autocomplete = "off"; R.ysUrl.spellcheck = false; p.appendChild(R.ysUrl);
  const rowb = h("div", "ek-ctl-row");
  R.ysOn = btnX("ÖNİZLE", "btn", () => ysOnizle(""));
  rowb.appendChild(R.ysOn); p.appendChild(rowb);
  R.ysMsg = h("p", "note"); p.appendChild(R.ysMsg);
  R.ysPrev = h("div", "ek-prev"); R.ysPrev.hidden = true; p.appendChild(R.ysPrev);
  p.appendChild(h("p", "note", "Kurmadan önce içeriği burada görürsün; onay vermeden hiçbir şey kurulmaz. Tanımadığın kaynaklardan gelen talimatlara dikkat: BLOOM'u istemediğin bir şeye yönlendirebilirler. Ona \"şu işi hep böyle yap, yetenek olarak kaydet\" diyerek de yetenek oluşturabilirsin."));
  buildKod(p);
}
function ysOnizle(secim){
  const url = R.ysUrl.value.trim();
  if(!url) return sonuc(R.ysMsg, "Bir GitHub adresi yapıştır.", true);
  R.ysOn.disabled = true; sonuc(R.ysMsg, "Bakılıyor…"); R.ysPrev.hidden = true;
  Promise.resolve(post("ek_yetenek", {eylem: "onizle", kaynak: url, secim: secim || ""})).then(r => { R.ysOn.disabled = false; ysGoster(r); })
    .catch(() => { R.ysOn.disabled = false; sonuc(R.ysMsg, "Bağlantı kurulamadı.", true); });
}
function ysGoster(r){
  r = r || {};
  R.ysPrev.replaceChildren();
  if(r.durum === "hata"){ R.ysPrev.hidden = true; return sonuc(R.ysMsg, r.mesaj || "Olmadı.", true); }
  if(r.durum === "kuruldu"){ R.ysPrev.hidden = true; R.ysUrl.value = ""; return sonuc(R.ysMsg, r.mesaj || "Kuruldu."); }
  if(r.durum === "sec"){
    sonuc(R.ysMsg, "Bu depoda birden fazla yetenek var; birini seç:");
    const w = h("div", "ek-ctl-row");
    for(const n of r.secenekler || []) w.appendChild(btnX(n, "btn ghost", () => ysOnizle(n)));
    R.ysPrev.appendChild(w); R.ysPrev.hidden = false; return;
  }
  sonuc(R.ysMsg, "");
  R.ysPrev.hidden = false;
  R.ysPrev.append(h("div", "ek-pv-k", "ÖNİZLEME · HENÜZ KURULMADI"), h("div", "ek-pv-ad", r.ad), h("div", "ek-pv-ac", r.aciklama));
  if((r.uyarilar || []).length){ const u = h("ul", "ek-warn"); for(const w of r.uyarilar) u.appendChild(h("li", null, w)); R.ysPrev.appendChild(u); }
  else R.ysPrev.appendChild(h("div", "ek-ok", "Otomatik taramada riskli bir ifade bulunmadı (bu, güvenli olduğunu garanti etmez)."));
  if(r.var) R.ysPrev.appendChild(h("div", "ek-warn1", "Aynı adlı yetenek zaten var; kurarsan üzerine yazılır."));
  const pre = h("pre", "ek-pre"); pre.textContent = r.onizleme || ""; R.ysPrev.appendChild(pre);
  R.ysPrev.appendChild(h("div", "ek-pv-f", "DOSYALAR: " + (r.dosyalar || []).join(", ")));
  const w = h("div", "ek-ctl-row");
  w.append(btnX("KUR", "btn", () => {
    guvenli(post("ek_yetenek", {eylem: "kur", kaynak: R.ysUrl.value.trim(), secim: r.secim || ""}), ysGoster);
  }), btnX("VAZGEÇ", "btn ghost", () => { R.ysPrev.hidden = true; R.ysPrev.replaceChildren(); }));
  R.ysPrev.appendChild(w);
}
function paintYetenek(){
  const L = (D && D.yetenekler) || [];
  R.ysList.replaceChildren();
  if(!L.length){ R.ysList.appendChild(h("div", "ek-empty", "Kurulu yetenek yok.")); return; }
  for(const y of L){
    const r = row(y.ad, y.aciklama.length > 160 ? y.aciklama.slice(0, 157) + "…" : y.aciklama);
    const t = sw(); t.setAttribute("aria-checked", String(!!y.acik));
    t.title = "Aç/kapat"; t.addEventListener("click", () => post("ek_yetenek", {eylem: "ac", ad: y.ad, on: !y.acik}));
    const x = btnX("SİL", "btn ghost", null); let armed = 0;
    x.addEventListener("click", () => {
      if(!armed){ armed = setTimeout(() => { armed = 0; x.textContent = "SİL"; }, 4000); x.textContent = "EMİN MİSİN?"; return; }
      clearTimeout(armed); armed = 0; post("ek_yetenek", {eylem: "sil", ad: y.ad});
    });
    const box = h("div", "ek-rbtn"); box.append(t, x); r.appendChild(box);
    R.ysList.appendChild(r);
  }
}

/* ---------------- KONSEY ---------------- */
function buildKonsey(p){
  p.appendChild(h("p", "lead", "Konsey: BLOOM zor ya da belirsiz bir karar verirken (ya da sen \"konseye sor\" dediğinde) birkaç bağımsız üyeye danışır. Üyeler rasyonel analist, şüpheci denetçi ve uygulayıcı rollerinde ayrı ayrı yanıt verir; anlaşamazlarsa birbirlerinin görüşünü sorgular, oylar kodla sayılır, hakem ortak kararı ve en güçlü karşı görüşü yazar. ÜCRETSİZ: yalnızca Gemini anahtarın yeter (üç rol aynı modelden gelir). Ücretsiz bir Groq / OpenRouter / Mistral / NVIDIA anahtarı da eklersen gerçekten FARKLI modeller de katılır. Sorunun metni bu servislere gider; gizli bilgi yazma."));
  R.kStat = h("div", "ek-stat", "—"); p.appendChild(R.kStat);
  const g = h("div", "ek-kp"); const gh = h("div", "ek-kp-h");
  gh.append(h("b", null, "GEMİNİ (mevcut anahtarın)"), h("span", "ek-kp-s", ""));
  R.kGemSt = gh.lastChild;
  const gt = btnX("TEST", "btn ghost", () => kTest("gemini", R.kGemMsg, gt));
  gh.appendChild(gt); R.kGemMsg = h("p", "note"); g.append(gh, R.kGemMsg); p.appendChild(g);
  R.kList = h("div", "ek-kplist"); p.appendChild(R.kList); R.kRows = {};
  p.appendChild(h("div", "ek-sec", "MODEL EKLE"));
  p.appendChild(h("p", "note", "Yeni bir ücretsiz modeli (ör. OpenRouter'daki bir :free modeli) buradan eklersin: sayfasının adresini yapıştır. Model konseye üye olur ve OpenRouter anahtarını kullanır. Ses, görüntü ya da ücretli modeller kabul edilmez."));
  R.mUrl = h("input", "ek-in"); R.mUrl.type = "text"; R.mUrl.spellcheck = false; R.mUrl.placeholder = "https://openrouter.ai/nvidia/nemotron-3.5-super-vl:free";
  R.mMsg = h("p", "note");
  R.mEkle = btnX("MODEL EKLE", "btn", () => {
    const u = R.mUrl.value.trim(); if(!u) return sonuc(R.mMsg, "Adres boş.", true);
    R.mEkle.disabled = true; sonuc(R.mMsg, "Kontrol ediliyor…");
    Promise.resolve(post("ek_konsey", {eylem: "model_ekle", girdi: u})).then(m => { R.mEkle.disabled = false; const bad = /^Hata/.test(m || ""); if(!bad) R.mUrl.value = ""; sonuc(R.mMsg, m || "", bad); })
      .catch(() => { R.mEkle.disabled = false; sonuc(R.mMsg, "Olmadı.", true); });
  });
  const mr = h("div", "ek-ctl-row"); mr.appendChild(R.mEkle);
  p.append(R.mUrl, mr, R.mMsg);
  p.appendChild(h("div", "ek-sec", "KONSEYE SOR"));
  R.kSoru = h("textarea", "ek-in ek-ta"); R.kSoru.rows = 3; R.kSoru.spellcheck = false;
  R.kSoru.placeholder = "Karar vermekte zorlandığın bir şeyi yaz…"; p.appendChild(R.kSoru);
  const rb = h("div", "ek-ctl-row");
  R.kSor = btnX("KONSEYE DANIŞ", "btn", () => {
    const q = R.kSoru.value.trim(); if(q.length < 6) return sonuc(R.kMsg, "Soru çok kısa.", true);
    R.kSor.disabled = true; sonuc(R.kMsg, "Konsey toplanıyor… (30-90 sn sürebilir)"); R.kOut.hidden = true;
    Promise.resolve(post("ek_konsey", {eylem: "sor", soru: q})).then(m => {
      R.kSor.disabled = false; const bad = /^Hata/.test(m || ""); sonuc(R.kMsg, bad ? m : "Tamam.", bad);
      if(!bad){ R.kOut.textContent = m || ""; R.kOut.hidden = false; }
    }).catch(() => { R.kSor.disabled = false; sonuc(R.kMsg, "Olmadı.", true); });
  });
  rb.appendChild(R.kSor); p.appendChild(rb);
  R.kMsg = h("p", "note"); R.kOut = h("pre", "ek-pre"); R.kOut.hidden = true; p.append(R.kMsg, R.kOut);
  R.kSon = h("p", "note"); p.appendChild(R.kSon);
}
function kTest(id, msgEl, b){
  b.disabled = true; sonuc(msgEl, "Deneniyor…");
  Promise.resolve(post("ek_konsey", {eylem: "dene", id})).then(m => { b.disabled = false; sonuc(msgEl, m || "", /^Hata|olmadı|başarısız/i.test(m || "")); })
    .catch(() => { b.disabled = false; sonuc(msgEl, "Bağlantı kurulamadı.", true); });
}
function kSatir(s){
  const w = h("div", "ek-kp"), head = h("div", "ek-kp-h");
  const st = h("span", "ek-kp-s", "");
  const t = sw(); t.title = "Konseye katılsın";
  t.addEventListener("click", () => post("ek_konsey", {eylem: "ac", id: s.id, on: !t._on}));
  const test = btnX("TEST", "btn ghost", () => kTest(s.id, msg, test));
  head.append(h("b", null, s.ad), st, t, test);
  const nt = h("p", "note ek-kp-n", s.not || "");
  const key = h("input", "ek-in"); key.type = "password"; key.autocomplete = "off"; key.spellcheck = false;
  key.placeholder = "API anahtarı (saklanır, ekranda gösterilmez)";
  let url, model, ad;
  w.append(head, nt);
  if(s.ozel){
    url = h("input", "ek-in"); url.type = "text"; url.placeholder = "Taban adres, ör. https://api.example.com/v1"; url.spellcheck = false;
    model = h("input", "ek-in"); model.type = "text"; model.placeholder = "Model adı"; model.spellcheck = false;
    ad = h("input", "ek-in"); ad.type = "text"; ad.placeholder = "Görünen ad (isteğe bağlı)"; ad.spellcheck = false;
    w.append(url, model, ad);
  }
  if(!s.ekstra) w.appendChild(key);
  const rb = h("div", "ek-ctl-row");
  const kaydet = btnX("KAYDET", "btn", () => {
    const run = () => {
      if(!key.value.trim()) return sonuc(msg, "Anahtar boş.", true);
      Promise.resolve(post("ek_konsey", {eylem: "kaydet", id: s.id, anahtar: key.value.trim()})).then(m => { key.value = ""; sonuc(msg, m || "", /^Hata/.test(m || "")); }).catch(() => sonuc(msg, "Olmadı.", true));
    };
    if(s.ozel){
      Promise.resolve(post("ek_konsey", {eylem: "ozel", url: url.value, model: model.value, ad: ad.value})).then(m => {
        if(/^Hata/.test(m || "")) return sonuc(msg, m, true);
        if(key.value.trim()) run(); else sonuc(msg, m || "");
      });
    }else run();
  });
  const kaldir = btnX("ANAHTARI KALDIR", "btn ghost", () => Promise.resolve(post("ek_konsey", {eylem: "kaydet", id: s.id, anahtar: ""})).then(m => sonuc(msg, m || "")).catch(() => {}));
  if(s.ekstra){
    const sil = btnX("MODELİ KALDIR", "btn ghost", () => Promise.resolve(post("ek_konsey", {eylem: "model_sil", id: s.id})).then(m => sonuc(msg, m || "")).catch(() => {}));
    rb.appendChild(sil);
  }else rb.append(kaydet, kaldir);
  w.appendChild(rb);
  const msg = h("p", "note"); w.appendChild(msg);
  const o = {el: w, st, t, test, nt, url, model, ad, key};
  return o;
}
function paintKonsey(){
  const K = (D && D.konsey) || {};
  const harici = (K.saglayicilar || []).filter(x => x.var && x.acik).length;
  R.kStat.dataset.s = K.gemini || harici ? "on" : "bad";
  R.kStat.textContent = (K.gemini ? "GEMİNİ HAZIR (3 ROL)" : "GEMİNİ ANAHTARI YOK") + "  ·  HARİCİ ÜYE " + harici + "  ·  TOPLAM " + (K.uye_sayisi || 0) + " ÜYE";
  R.kGemSt.textContent = K.gemini ? "HAZIR" : "ANAHTAR YOK";
  const ids = new Set((K.saglayicilar || []).map(x => x.id));
  for(const id of Object.keys(R.kRows)) if(!ids.has(id)){ R.kRows[id].el.remove(); delete R.kRows[id]; }
  for(const s of K.saglayicilar || []){
    let o = R.kRows[s.id];
    if(!o){ o = R.kRows[s.id] = kSatir(s); R.kList.appendChild(o.el); }
    o.t._on = !!s.acik; setSwitch(o.t, s.acik && s.var);
    o.st.textContent = s.var ? (s.acik ? "AÇIK" : "KAPALI") : "ANAHTAR YOK";
    o.st.dataset.s = s.var && s.acik ? "on" : "off";
    o.key.placeholder = s.var ? "Anahtar kayıtlı — değiştirmek için yenisini yaz" : "API anahtarı (saklanır, ekranda gösterilmez)";
    o.nt.textContent = (s.not || "") + (s.model ? "  Model: " + s.model : "") + (s.url ? "  ·  Anahtar al: " + s.url.replace(/^https?:\/\//, "") : "");
  }
  const son = K.son || {};
  R.kSon.textContent = son.t ? "SON KONSEY " + new Date(son.t * 1000).toLocaleTimeString("tr-TR", {hour: "2-digit", minute: "2-digit"}) + " · " + (son.ozet || "") : "";
}

/* ---------------- BELLEK ---------------- */
function buildBellek(p){
  p.appendChild(h("p", "lead", "Konuşma geçmişi yalnızca bu bilgisayarda tutulur ve yaklaşık 1 ay sonra kendiliğinden silinir. Konuşmada önemli bir bilgi geçtiyse (ör. bir karar, tarih, senin hakkında kalıcı bir şey), silinmeden önce kalıcı hafızaya aktarılır ve orada kalır."));
  const rHist = row("KONUŞMALARI HATIRLA", "");
  R.swHist = sw(); rHist.appendChild(R.swHist); R.histSmall = rHist.small;
  R.swHist.addEventListener("click", () => post("ek_gecmis_ac", {on: !(D && D.gecmis && D.gecmis.acik)}));
  const rAuto = row("ÖNEMLİ BİLGİYİ KALICI SAKLA", "");
  R.swAuto = sw(); rAuto.appendChild(R.swAuto); R.autoSmall = rAuto.small;
  R.swAuto.addEventListener("click", () => post("ek_bellek", {eylem: "ac", on: !(D && D.bellek && D.bellek.otomatik)}));
  const rNow = row("ŞİMDİ AKTAR", "Son konuşmalardaki önemli bilgileri hemen kalıcı hafızaya yazar (Ayarlar › HAFIZA'da görünür ve silinebilir).");
  R.bNow = btnX("AKTAR", "btn ghost", () => {
    R.bNow.disabled = true; sonuc(R.bMsg, "Taranıyor…");
    Promise.resolve(post("ek_bellek", {eylem: "ozetle"})).then(m => { R.bNow.disabled = false; sonuc(R.bMsg, m, /^Hata/.test(m || "")); })
      .catch(() => { R.bNow.disabled = false; sonuc(R.bMsg, "Olmadı.", true); });
  });
  rNow.appendChild(R.bNow);
  R.bMsg = h("p", "note");
  const rDel = row("KONUŞMA GEÇMİŞİNİ SİL", "Yalnızca bu bilgisayardaki konuşma geçmişi silinir. Kalıcı hafızaya aktarılmış bilgiler kalır (Ayarlar › HAFIZA).");
  R.bDel = h("button", "btn ghost", "SİL"); R.bDel.type = "button"; rDel.appendChild(R.bDel);
  let armed = 0;
  R.bDel.addEventListener("click", () => {
    if(!armed){ armed = setTimeout(() => { armed = 0; R.bDel.textContent = "SİL"; }, 4000); R.bDel.textContent = "EMİN MİSİN?"; return; }
    clearTimeout(armed); armed = 0; R.bDel.textContent = "SİL"; post("ek_gecmis_sil", {});
  });
  p.append(rHist, rAuto, rNow, R.bMsg, rDel);
  R.bStat = h("p", "note"); p.appendChild(R.bStat);
  p.appendChild(h("div", "ek-sec", "ÖĞRENDİKLERİM"));
  p.appendChild(h("p", "note", "BLOOM her konuşmadan bir şey öğrenmez. Yalnızca seni yanlış anladığında, bir aracı yanlış kullanıp hata aldığında ya da sen kalıcı bir kural verdiğinde, kanıtıyla birlikte kısa bir ders yazar. Yanlış öğrendiğini düşünüyorsan ✕ ile sil."));
  R.dersListe = h("div", "ek-dersler"); p.appendChild(R.dersListe); R.dersAnahtar = null;
}
function paintDersler(){
  const L = (D && D.ders_listesi) || [];
  const key = L.join("\u0001");
  if(R.dersAnahtar === key) return;
  R.dersAnahtar = key;
  R.dersListe.replaceChildren();
  if(!L.length){ R.dersListe.appendChild(h("div", "ek-empty", "Henüz öğrenilmiş bir ders yok — sorun değil: gerek olmadıkça öğrenmez.")); return; }
  for(const t of L){
    const r = h("div", "ek-ders"); r.appendChild(h("span", "ek-ders-t", t));
    const x = btnX("✕", "btn ghost ek-ders-x", () => { x.disabled = true; post("ek_ders", {eylem: "sil", metin: t}); });
    x.title = "Bu dersi unut"; r.appendChild(x); R.dersListe.appendChild(r);
  }
}
function paintBellek(){
  paintDersler();
  const g = (D && D.gecmis) || {}, b = (D && D.bellek) || {};
  setSwitch(R.swHist, g.acik);
  R.histSmall.textContent = g.acik
    ? "Konuştuklarımız yalnızca bu bilgisayarda saklanır; BLOOM sonraki konuşmada hatırlar. Şu an " + (g.adet || 0) + " kayıt var. Sen sözünü kesince yarım kalan cevap da kaydedilir."
    : "Kapalı: yeni konuşmalar kaydedilmez ve hatırlanmaz.";
  setSwitch(R.swAuto, b.otomatik);
  R.autoSmall.textContent = b.otomatik
    ? "Konuşma bitince önemli bilgiler Gemini ile ayıklanıp kalıcı hafızaya yazılır (konuşma metni bu iş için Gemini'ye gider; şifre/kart gibi gizli veriler alınmaz)."
    : "Kapalı: yalnızca sen \"bunu önemli say\" dersen aktarılır.";
  const son = b.son && b.son.t ? new Date(b.son.t * 1000) : null;
  R.bStat.textContent = (b.kayitli || 0) + " ÖNEMLİ BİLGİ KAYITLI · " + (b.bekleyen || 0) + " SATIR TARANMAYI BEKLİYOR · GEÇMİŞ " + (b.gun || 30) + " GÜN" +
    (son ? " · SON AKTARIM " + pad(son.getDate()) + "." + pad(son.getMonth() + 1) + " " + pad(son.getHours()) + ":" + pad(son.getMinutes()) : "");
}


/* ---------------- SES sekmesi ---------------- */
function segBtn(label, key, fn){ const b = h("button", "ek-seg", label); b.type = "button"; b.dataset.k = key; b.addEventListener("click", () => fn(key)); return b; }
function sesAyar(anahtar, deger){ post("ek_ses", {eylem: "ayar", anahtar, deger}); }
function buildSes(p){
  p.appendChild(h("p", "lead", "BLOOM penceresi öndeyken her zamanki gibi dinler: söz söylemek yeter. Başka bir pencerede çalışırken ya da arkada müzik/video çalarken yalnızca \"Hey Bloom\" deyince dinler. \"Hey Bloom\" tanıması bu bilgisayarda yapılır; kapalıyken hiçbir ses internete gitmez."));
  const rWake = row("\"HEY BLOOM\" İLE ÇAĞIR", "");
  R.swWake = sw(); rWake.appendChild(R.swWake); R.wakeSmall = rWake.small;
  R.swWake.addEventListener("click", () => sesAyar("uyandir_acik", !(D && D.ses && D.ses.uyandir_acik)));
  const rYaz = row("ARKADA SES ÇALARKEN YAZILI KONUŞ", "");
  R.swYaz = sw(); rYaz.appendChild(R.swYaz); R.yazSmall = rYaz.small;
  R.swYaz.addEventListener("click", () => sesAyar("yazili_mod", !(D && D.ses && D.ses.yazili_mod)));
  const rHas = row("ÇAĞRI HASSASİYETİ", "Yüksek: çağrıyı daha kolay duyar ama yanlış uyanabilir. Düşük: yalnızca net söylenince.");
  const seg = h("div", "ek-segs"); R.segs = {};
  for(const [k, l] of [["yuksek", "YÜKSEK"], ["orta", "ORTA"], ["dusuk", "DÜŞÜK"]]){ const b = segBtn(l, k, v => sesAyar("uyandir_hassasiyet", v)); R.segs[k] = b; seg.appendChild(b); }
  rHas.appendChild(seg);
  R.sesDurum = h("p", "note"); R.sesNot = h("p", "note");
  p.append(rWake, rYaz, rHas, R.sesDurum, R.sesNot);
  p.appendChild(h("div", "ek-sec", "EKRAN"));
  const ayarSatir = (baslik, kucuk, anahtar, oku) => {
    const r = row(baslik, kucuk); const b = sw(); r.appendChild(b);
    b.addEventListener("click", () => post("ek_ayar", {anahtar, deger: !oku()}));
    p.appendChild(r); return b;
  };
  R.swCanli = ayarSatir("KONUŞURKEN YAZIYI CANLI GÖSTER", "BLOOM konuşurken söylediği metin ekranda aynı anda belirir.", "canli_acik", () => !!(D && D.canli && D.canli.acik));
  R.swSenk = ayarSatir("YAZI SESLE SENKRON AKSIN", "Açık: yazı sesin hızında akar. Kapalı: metin gelir gelmez görünür.", "canli_senkron", () => !!(D && D.canli && D.canli.senkron));
  R.swHava = ayarSatir("HAVA DURUMU YALNIZCA DEĞİŞİNCE YENİLENSİN", "Açık: saat başı ya da konum/uyku sonrası bir kez bakar; sürekli sorgulamaz.", "hava_akilli", () => !!(D && D.hava && D.hava.akilli));
}
const MOD_YAZI = {serbest: "SERBEST — pencere öndeyken sürekli dinliyorum", cagri: "ÇAĞRI — \"Hey Bloom\" deyince dinlerim", yazili: "YAZILI — arkada ses çalıyor; cevabım ekranda yazılı, çağırmak için \"Hey Bloom\""};
function paintSes(){
  const s = (D && D.ses) || {};
  setSwitch(R.swWake, s.uyandir_acik);
  setSwitch(R.swYaz, s.yazili_mod);
  R.wakeSmall.textContent = s.uyandir_acik
    ? (s.uyandir_var ? "Açık. Başka pencere öndeyken ya da arkada ses çalarken yalnızca \"Hey Bloom\" ile dinlerim." : "Açık ama çağrı modeli yüklenemedi" + (s.uyandir_hata ? " (" + s.uyandir_hata + ")" : "") + ": şimdilik eskisi gibi her zaman dinlerim.")
    : "Kapalı: mikrofon her zaman açık dinler (başka pencere öndeyken de).";
  R.yazSmall.textContent = s.yazili_mod
    ? "Açık: Spotify, video vb. çalarken sesim kapanır; komutları yine yaparım ve cevabı sohbete yazarım. Müziğe dokunmam."
    : "Kapalı: arkada ses çalarken de sesli konuşurum (\"Hey Bloom\" yine gerekir).";
  for(const k in R.segs) R.segs[k].classList.toggle("on", s.hassasiyet === k);
  setSwitch(R.swCanli, D && D.canli && D.canli.acik); setSwitch(R.swSenk, D && D.canli && D.canli.senkron); setSwitch(R.swHava, D && D.hava && D.hava.akilli);
  R.sesDurum.textContent = "ŞU AN: " + (MOD_YAZI[s.mod] || "—") + (s.uyanma_sayisi ? "  ·  BU OTURUMDA " + s.uyanma_sayisi + " KEZ ÇAĞRILDI" : "");
  R.sesNot.textContent = s.odak === false ? "BLOOM penceresi şu an arkada." : (s.medya ? "Arkada ses çalıyor." : "");
}

/* ---------------- ertelenmiş komutlar ---------------- */
function paintSonra(){
  if(!R.sonraListe) return;
  const l = (D && D.sonra) || [];
  R.sonraBaslik.hidden = R.sonraListe.hidden = !l.length;
  R.sonraListe.replaceChildren();
  for(const j of l){
    const r = h("div", "ek-sonra-r");
    r.append(h("span", null, j.kosul + " → " + j.ne));
    const x = h("button", "ek-x2", "✕"); x.type = "button"; x.title = "İptal et";
    x.addEventListener("click", () => post("ek_sonra", {eylem: "iptal", id: j.id}));
    r.appendChild(x); R.sonraListe.appendChild(r);
  }
}

/* ---------------- FİKİR ALANIM (BLOOM'un içinde) ---------------- */
const fbtn = h("button", "ctl ek-fikir");
fbtn.id = "t-ekfikir"; fbtn.type = "button"; fbtn.title = "Fikir Alanım: görevler, fikirler, hafta (F8)";
fbtn.innerHTML = '<i class="dot"></i>FİKİR <b id="t-ekfikir-n"></b>';
{
  const eski = $id("t-fikir"); if(eski) eski.remove();           // eski ayrı Fikir sürümünün düğmesi/katmanı
  const eskiOv = $id("ov-fikir"); if(eskiOv) eskiOv.remove();
  const bar = $id("topbar");
  if(bar) bar.insertBefore(fbtn, btn);
}
const fN = fbtn.querySelector("#t-ekfikir-n");
const FIKIR = {ov: null, frame: null, yuklu: false, store: null, adres: ""};
const FVARS = ["--c", "--rgb", "--accent", "--arg", "--deep", "--ink", "--dim", "--faint", "--alert"];
function fikirTema(){
  const cs = getComputedStyle(document.documentElement), out = {};
  for(const v of FVARS){ const x = cs.getPropertyValue(v).trim(); if(x) out[v] = x; }
  return out;
}
function fikirIt(){ if(FIKIR.yuklu && FIKIR.frame && FIKIR.frame.contentWindow) FIKIR.frame.contentWindow.postMessage({jarvis: "theme", vars: fikirTema()}, "*"); }
function fikirKur(){
  if(FIKIR.ov) return true;
  const ov = h("div", "overlay"); ov.id = "ov-ekfikir";
  const sheet = h("div", "sheet fikirsheet"); sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-label", "Fikir Alanım");
  const bar = h("div", "fk-bar");
  const st = h("em"); st.dataset.s = "session";
  const close = h("button", "close", "✕"); close.type = "button"; close.title = "Kapat (Esc)"; close.setAttribute("aria-label", "Kapat");
  close.addEventListener("click", () => { if(typeof closeOverlays === "function") closeOverlays(); else ov.classList.remove("on"); });
  bar.append(h("b", null, "FİKİR ALANIM"), h("span", null, "GÖREV · FİKİR · HAFTA — BLOOM BUNLARI GÖRÜR VE YÖNETİR"), st, close);
  const fr = document.createElement("iframe"); fr.id = "ekfikir-frame"; fr.title = "Fikir Alanım";
  fr.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
  fr.addEventListener("load", fikirIt);
  sheet.append(bar, fr); ov.appendChild(sheet); document.body.appendChild(ov);
  ov.addEventListener("mousedown", e => { if(e.target === ov && typeof closeOverlays === "function") closeOverlays(); });
  Object.assign(FIKIR, {ov, frame: fr, store: st});
  return true;
}
function fikirAc(){
  fikirKur();
  const adres = D && D.fikir && D.fikir.adres;
  if(!adres){ post("ek_fikir", {eylem: "hazirla"}); fN.textContent = ""; }
  if(adres && !FIKIR.yuklu){ FIKIR.yuklu = true; FIKIR.adres = adres; FIKIR.frame.src = adres; }
  if(typeof openOverlay === "function") openOverlay("ov-ekfikir"); else FIKIR.ov.classList.add("on");
  fikirIt();
  setTimeout(() => { try{ FIKIR.frame.focus(); }catch(_){} }, 80);
}
function fikirDeg(){ if(FIKIR.ov && FIKIR.ov.classList.contains("on")) closeOverlays(); else fikirAc(); }
fbtn.addEventListener("click", fikirAc);
// F8 (eski sürümün dinleyicisinden önce, yakalama aşamasında)
window.addEventListener("keydown", e => {
  if(e.key !== "F8" || (typeof Onboard !== "undefined" && Onboard.on)) return;
  e.preventDefault(); e.stopImmediatePropagation(); fikirDeg();
}, true);
window.addEventListener("message", e => {
  const m = e.data;
  if(!FIKIR.frame || e.source !== FIKIR.frame.contentWindow || !m || typeof m !== "object") return;
  if(m.fikir === "ready") fikirIt();
  else if(m.fikir === "store" && FIKIR.store){
    const t = {saved: "● KAYIT AÇIK", error: "! KAYDEDİLEMEDİ — TEKRAR DENENİYOR", session: "○ GEÇİCİ: KAPANINCA SİLİNİR"};
    FIKIR.store.dataset.s = t[m.state] ? m.state : "session"; FIKIR.store.textContent = t[m.state] || t.session;
  }
  else if(m.fikir === "close") closeOverlays();
  else if(m.fikir === "key" && (m.key === "F4" || m.key === "F6")) document.dispatchEvent(new KeyboardEvent("keydown", {key: m.key, bubbles: true, cancelable: true}));
  else if(m.fikir === "key" && m.key === "F8") fikirDeg();
  else if(m.fikir === "ac" && m.url === "https://studytracker.com.tr") post("ek_ac", {url: m.url});
});
new MutationObserver(() => {
  if(FIKIR.wait || !FIKIR.ov || !FIKIR.ov.classList.contains("on")) return;
  FIKIR.wait = setTimeout(() => { FIKIR.wait = 0; fikirIt(); }, 160);
}).observe(document.documentElement, {attributes: true, attributeFilter: ["style"]});
function fikirYenile(){
  // Yapay zekâ ya da anımsatıcı Fikir verisini değiştirdi: sayfa kullanıcı yazmıyorsa kendini tazeler (kararı sayfa verir);
  // yazıyorsa sonraki kayıtta (409) tazelenir.
  if(!FIKIR.yuklu || !FIKIR.frame || !FIKIR.frame.contentWindow) return;
  try{ FIKIR.frame.contentWindow.postMessage({jarvis: "refresh"}, "*"); }catch(_){}
}
function paintFikir(){
  const f = (D && D.fikir) || {};
  fN.textContent = f.acik ? String(f.acik) : "";
  fbtn.dataset.ek = f.acik ? "on" : "off";
  if(f.adres && f.adres !== FIKIR.adres && FIKIR.yuklu){ FIKIR.adres = f.adres; FIKIR.frame.src = f.adres; }   // port değiştiyse
}

/* ---------------- ses modu çipi (yalnızca serbest dışında görünür) ---------------- */
const chip = h("button", "ctl ek-mod");
chip.id = "t-ekmod"; chip.type = "button"; chip.hidden = true;
chip.innerHTML = '<i class="dot"></i><span id="t-ekmod-l"></span>';
{ const bar = $id("topbar"); if(bar) bar.insertBefore(chip, fbtn); }
const chipL = chip.querySelector("#t-ekmod-l");
chip.addEventListener("click", () => openPanel("ses"));
function paintMod(){
  const s = (D && D.ses) || {}, m = s.mod || "serbest";
  chip.hidden = m === "serbest";
  chip.dataset.mod = m;
  chipL.textContent = m === "yazili" ? "YAZILI · \"HEY BLOOM\"" : "\"HEY BLOOM\"";
  chip.title = MOD_YAZI[m] || "";
  document.body.classList.toggle("ek-yazili", m === "yazili");
}
let flashT = 0;
function uyandi(){
  chip.classList.add("flash"); chipL.dataset.old = chipL.dataset.old || chipL.textContent; chipL.textContent = "DİNLİYORUM";
  clearTimeout(flashT);
  flashT = setTimeout(() => { chip.classList.remove("flash"); chipL.textContent = chipL.dataset.old || ""; chipL.dataset.old = ""; paintMod(); }, 2200);
}



/* ---------------- KENDİ KODU: salt okunur izin kartı (YETENEKLER sekmesinin altı) ---------------- */
function buildKod(p){
  p.appendChild(h("div", "ek-sec", "KENDİ KODUNA BAKMA İZNİ"));
  p.appendChild(h("p", "note", "Açıkken BLOOM, hata ayıklamak için kendi kaynak kodunu ve günlüğünü SALT OKUNUR inceler. Hiçbir şey yazmaz, silmez, çalıştırmaz; ayarlarına, belleğine, anahtarlarına bakamaz. Düzeltmeyi yalnızca öneri dosyası olarak yazar, uygulamak sana kalır."));
  const r = row("KENDİ KODUNU OKUYABİLİR", "Kapalıyken kendi koduna bakamaz.");
  R.kodSw = sw(); r.appendChild(R.kodSw);
  R.kodSw.addEventListener("click", () => { R.kodSw.disabled = true; guvenli(post("ek_kod_izin", {ver: !(D && D.kod && D.kod.izin)}), m => { R.kodSw.disabled = false; sonuc(R.kodMsg, m); }); });
  p.appendChild(r);
  R.kodMsg = h("p", "note"); p.appendChild(R.kodMsg);
  R.kodBilgi = h("p", "note"); p.appendChild(R.kodBilgi);
}
function paintKod(){
  if(!R.kodSw) return;
  const k = (D && D.kod) || {};
  setSwitch(R.kodSw, k.izin);
  R.kodBilgi.textContent = (k.kaynak ? "Kaynak klasörü bulundu." : "Kaynak klasörü bulunamadı (paketle gelen \"bloom-kaynak\" klasörü exe'nin yanında olmalı).") +
    (k.oneri ? " Bekleyen yama önerisi: " + k.oneri + " (veri klasörü › ek › yama-onerileri)." : "");
}

/* ---------------- YAYIN modu: sekme + üst çubuk rozeti ---------------- */
const yrozet = h("button", "ctl ek-yayin");
yrozet.id = "t-ekyayin"; yrozet.type = "button"; yrozet.hidden = true; yrozet.title = "Yayın modu açık: kişisel bilgiler sahteyle değişiyor. Ayar için tıkla.";
yrozet.innerHTML = '<i class="dot"></i><span>YAYIN</span>';
{ const bar = $id("topbar"); if(bar) bar.insertBefore(yrozet, chip); }
yrozet.addEventListener("click", () => openPanel("yayin"));
function paintYayinChip(){ const y = (D && D.yayin) || {}; yrozet.hidden = !y.acik; document.body.classList.toggle("ek-yayinda", !!y.acik); }
const YAYIN_KAT = [["konum", "KONUM", "Ekranda, haritada ve asistanın sözünde yer sahte şehir olur."],
  ["hava", "HAVA DURUMU", "Hava paneli sahte şehrin havasını gösterir."],
  ["kisiler", "KİŞİLER VE NUMARALAR", "Rehber/WhatsApp adları takma adla, numaralar ••• ile görünür. \"Ayşe'ye yaz\" dediğinde yine doğru kişiye gider."],
  ["hafiza", "HAFIZA", "Asistana kişisel hafıza verilmez; Ayarlar › Hafıza boş görünür (sahte değil, gizli)."],
  ["fikir", "FİKİR ALANIM", "Demo verisiyle açılır. Gerçek verin diskte aynen durur; yayındaki düzenlemeler kaydedilmez."],
  ["kimlik", "AD VE BİLGİSAYAR ADI", "Adın, Windows kullanıcı adın ve bilgisayar adın sahtesiyle görünür (dosya yolları dahil)."]];
function buildYayin(p){
  p.appendChild(h("p", "lead", "Canlı yayın ya da ekran paylaşımı için. Açıkken kişisel bilgiler HEM ekranda HEM asistanın söylediklerinde sahte değerlerle değişir; gerçek verilerin bilgisayarında olduğu gibi kalır. Mikrofona söylediğin gerçek bir ad ya da yer yayında DUYULUR: yayında takma adı kullan. Başka programlar ve pencereler bu modun dışındadır."));
  const rMain = row("YAYIN MODU", "Açılınca asistan oturumu yenilenir (yeni talimatla).");
  R.yMain = sw(); rMain.appendChild(R.yMain);
  R.yMain.addEventListener("click", () => { R.yMain.disabled = true; guvenli(post("ek_yayin", {acik: !(D && D.yayin && D.yayin.acik)}), m => { R.yMain.disabled = false; sonuc(R.yMsg, m); }); });
  p.appendChild(rMain);
  p.appendChild(h("div", "ek-sec", "NELER GİZLENSİN"));
  R.yKat = {};
  for(const [k, label, info] of YAYIN_KAT){
    const r = row(label, info); const s = sw(); r.appendChild(s); R.yKat[k] = s;
    s.addEventListener("click", () => { const cur = !!(D && D.yayin && D.yayin.kat && D.yayin.kat[k]); const kat = {}; kat[k] = !cur; post("ek_yayin", {kat}); });
    p.appendChild(r);
  }
  p.appendChild(h("div", "ek-sec", "SAHTE DEĞERLER (yalnızca bunlar görünür)"));
  const dl = h("datalist"); dl.id = "ek-yayin-yerler"; p.appendChild(dl); R.yDl = dl;
  const alan = (etiket, ipucu) => { const w = h("label", "ek-num ek-yayin-alan"); const i = h("input", "ek-in"); i.type = "text"; i.maxLength = 40; i.autocomplete = "off"; i.spellcheck = false; i.placeholder = ipucu;
    i.addEventListener("input", () => { R.yKirli = true; }); w.append(h("span", null, etiket), i); w.input = i; return w; };
  R.yKonum = alan("KONUM", "Lizbon"); R.yKonum.input.setAttribute("list", "ek-yayin-yerler");
  R.yAd = alan("AD", "Alex"); R.yBil = alan("BİLGİSAYAR ADI", "DESKTOP-7K2M9X");
  const kaydet = btnX("KAYDET", "btn", () => {
    kaydet.disabled = true; sonuc(R.yMsg, "Kaydediliyor…");
    Promise.resolve(post("ek_yayin", {konum: R.yKonum.input.value, ad: R.yAd.input.value, bilgisayar: R.yBil.input.value})).then(m => { kaydet.disabled = false; R.yKirli = false; sonuc(R.yMsg, m, /Uyarı|Hata/.test(m || "")); })
      .catch(() => { kaydet.disabled = false; sonuc(R.yMsg, "Olmadı.", true); });
  });
  R.yMsg = h("p", "note");
  p.append(R.yKonum, R.yAd, R.yBil, kaydet, R.yMsg);
}
function paintYayin(){
  if(!R.yMain) return;
  const y = (D && D.yayin) || {}, kat = y.kat || {}, s = y.sahte || {};
  setSwitch(R.yMain, y.acik);
  for(const k in R.yKat) setSwitch(R.yKat[k], kat[k]);
  if(!R.yKirli && document.activeElement !== R.yKonum.input && document.activeElement !== R.yAd.input && document.activeElement !== R.yBil.input){
    R.yKonum.input.value = s.konum || ""; R.yAd.input.value = s.ad || ""; R.yBil.input.value = s.bilgisayar || "";
  }
  const yerler = y.yerler || [];
  if(R.yDl.childElementCount !== yerler.length){ R.yDl.replaceChildren(); for(const v of yerler){ const o = h("option"); o.value = v; R.yDl.appendChild(o); } }
  const anahtar = (y.acik ? "1" : "0") + (y.acik && kat.fikir ? "f" : "");
  if(R.yAnahtar !== undefined && R.yAnahtar !== anahtar){ try{ if(FIKIR.yuklu && FIKIR.frame && FIKIR.frame.src) FIKIR.frame.src = FIKIR.frame.src; }catch(e){} }
  R.yAnahtar = anahtar;
}

function openPanel(tab){
  build();
  paint();
  if(typeof tab === "string" && P[tab]) showTab(tab);
  if(typeof openOverlay === "function") openOverlay("ov-ek"); else R.ov.classList.add("on");
}

/* ---------------- çizim ---------------- */
function remaining(){
  const p = D && D.pomo;
  if(!p || !p.aktif) return 0;
  if(p.duraklat) return p.kalan || 0;
  return Math.max(0, (p.biter || 0) - Date.now() / 1000);
}

function paintTop(){
  if(typeof paintMod === "function"){ try{ paintMod(); paintFikir(); paintYayinChip(); }catch(e){} }
  const odak = !!(D && D.odak && D.odak.on), p = D && D.pomo && D.pomo.aktif ? D.pomo : null;
  btn.dataset.ek = p ? (p.faz === "odak" ? "odak" : "mola") : (odak ? "odak" : "off");
  document.body.classList.toggle("ek-odak", odak);
  if(p) stateEl.textContent = (p.duraklat ? "⏸ " : "") + mmss(remaining());
  else stateEl.textContent = odak ? "AÇIK" : "";
  btn.title = p ? p.etiket + (p.gorev ? " · " + p.gorev : "") : (odak ? "Pomodoro açık" : "Pomodoro ve ses ayarları");
}

function setSwitch(b, on){ b.setAttribute("aria-checked", String(!!on)); }

function paint(){
  paintTop();
  if(!built || !D) return;
  const p = D.pomo || {}, on = !!p.aktif;
  R.setup.hidden = on; R.ctl.hidden = !on; R.pomo.dataset.state = on ? (p.duraklat ? "pause" : p.faz) : "idle";
  if(on){
    R.phase.textContent = (p.etiket || "POMODORO").toUpperCase() + (p.duraklat ? " · DURAKLATILDI" : "");
    R.big.textContent = mmss(remaining());
    R.task.textContent = p.gorev ? p.gorev : "";
    const tot = p.toplam || 1;
    R.fill.style.width = Math.max(0, Math.min(100, 100 - remaining() / tot * 100)) + "%";
    R.bPause.textContent = p.duraklat ? "DEVAM" : "DURAKLAT";
  }else{
    R.phase.textContent = "HAZIR";
    R.big.textContent = pad(+R.nWork.input.value || 25) + ":00";
    R.task.textContent = ""; R.fill.style.width = "0%";
  }
  const b = D.bugun || {n: 0, dk: 0};
  R.today.textContent = "BUGÜN: " + b.n + " POMODORO · " + b.dk + " DAKİKA ODAK";
  setSwitch(R.swPerf, typeof SETTINGS === "object" && SETTINGS && SETTINGS.render_quality === "low");
  paintBellek(); paintSpotify(); paintYetenek(); paintKonsey(); paintSes(); paintSonra(); paintYayin(); paintKod();
  const bits = [];
  bits.push(D.konum ? "KONUM: " + D.konum + " (Ayarlar'dan)" : "KONUM: ayarlanmadı (IP ya da Windows konumu kullanılmaz)");
  bits.push((D.dersler || 0) + " ÖĞRENİLMİŞ DERS");
  R.foot.textContent = bits.join("  ·  ") + "  ·  v" + (D.surum || "");
}

function schedule(){
  const p = D && D.pomo;
  const need = !!(p && p.aktif && !p.duraklat);
  if(need && !tick){ tick = setInterval(() => { if(document.visibilityState === "visible") paint(); }, 1000); }
  else if(!need && tick){ clearInterval(tick); tick = 0; }
}

/* ---------------- araştırma kaynak kartı ---------------- */
let card = null;
function showSources(m){
  if(!card){
    card = h("div", "ek-src"); card.id = "ek-src";
    document.body.appendChild(card);
  }
  card.replaceChildren();
  const x = h("button", "ek-x", "✕"); x.type = "button"; x.title = "Kapat"; x.addEventListener("click", () => { card.classList.remove("on"); });
  card.appendChild(x);
  card.appendChild(h("div", "ek-src-k", m.etiket || "ARAŞTIRMA"));
  card.appendChild(h("div", "ek-src-q", m.soru || ""));
  if(m.ozet){ const rp = h("div", "ek-src-t"); rp.textContent = m.ozet; card.appendChild(rp); }
  const list = h("div", "ek-src-l");
  (m.kaynaklar || []).forEach((s, i) => {
    const a = h("button", "ek-link"); a.type = "button";
    a.append(h("b", null, String(i + 1)), h("span", null, s.baslik || s.alan || s.url), h("small", null, s.alan || ""));
    a.addEventListener("click", () => post("ek_ac", {url: s.url}));
    list.appendChild(a);
  });
  card.appendChild(list);
  const n = (m.kaynaklar || []).length;
  card.appendChild(h("div", "ek-src-n", n ? (m.acildi ? m.acildi + " SEKME TARAYICIDA AÇILDI · " : "") + "KAYNAĞA DOKUN, TARAYICIDA AÇILSIN" : "KAYNAK BULUNAMADI"));
  card.classList.add("on");
}

/* ---------------- canlı döküm ----------------
   Python (ek_canli.py) konuşulan/duyulan metni parça parça yollar: ai için SESİN ÇALINDIĞI hıza göre, you için hemen.
   Gerçek satır (turn_complete → J.line) geldiğinde canlı satır onunla değişir; ses bitmeden ai satırı yazılmaz. */
const LIVE = {};                       // who → {row, lt, text, t, done, stash, fb}
const PRE = {ai: "", you: ""};         // yarıda kesilen cevabın ham metni: V4'ün gerçek satırı bununla başlar → baştan atılır
const RECENT = {};                     // who → {row, t, fb}: son kalıcı yapılan satır
let ORIG_LINE = null;
function logBox(){ return $id("chat"); }
function altaKaydir(box, stick){ if(box && stick) box.scrollTo({top: box.scrollHeight, behavior: "instant"}); }
function canliSatir(who){
  let L = LIVE[who];
  if(L) return L;
  const row = h("div", "sub live " + who), lt = h("span", "ek-lt"), node = document.createTextNode("");
  lt.appendChild(node); row.append(lt);
  const log = $id("chat-log"), box = logBox();
  if(!log) return null;
  const stick = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  log.appendChild(row);
  L = LIVE[who] = {row, lt, node, text: "", shown: 0, acc: 0, t: Date.now(), done: false, stash: null, bitir: null};
  altaKaydir(box, stick);
  return L;
}
/* Yumuşak yazım: gelen metin (L.text) parça parça ve düzensiz gelir; ekranda gösterilen kısım (L.shown) her karede,
   bekleyen miktara göre ayarlanan hızla ilerler (az birikmişse yavaş, çok birikmişse hızlı) → kesik kesik değil, akıcı. */
let pumpRaf = 0, pumpT = 0;
function pump(now){
  pumpRaf = 0;
  const dt = Math.min(0.1, Math.max(0.001, (now - (pumpT || now - 16)) / 1000)); pumpT = now;
  let aktif = false;
  for(const who of Object.keys(LIVE)){
    const L = LIVE[who], bekleyen = L.text.length - L.shown;
    if(bekleyen > 0){
      aktif = true;
      const hiz = Math.max(26, bekleyen / (L.done ? 0.12 : 0.55));        // karakter/sn: birikme ~0,5 sn'de erir
      L.acc += hiz * dt;
      const n = Math.min(bekleyen, Math.floor(L.acc));
      if(n > 0){
        L.acc -= n;
        const box = logBox(), stick = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 80;
        L.shown += n; L.node.nodeValue = L.text.slice(0, L.shown);
        altaKaydir(box, stick);
      }
    }
    if(L.text.length === L.shown && L.bitir){ const f = L.bitir; L.bitir = null; f(); }
  }
  if(aktif || Object.values(LIVE).some(L => L.bitir)) pumpRaf = requestAnimationFrame(pump);
  else pumpT = 0;
}
function pumpBaslat(){ if(!pumpRaf) pumpRaf = requestAnimationFrame(pump); }
function canliYaz(L, text){
  let ortak = 0;
  const n = Math.min(L.text.length, text.length);
  while(ortak < n && L.text.charCodeAt(ortak) === text.charCodeAt(ortak)) ortak++;
  L.text = text;
  if(L.shown > ortak){ L.shown = ortak; L.node.nodeValue = text.slice(0, ortak); }     // metin değiştiyse ortak başlangıca dön
  pumpBaslat();
}
/* Gerçek satır canlı satırın YERİNE sessizce geçer: önce gerçek satır eklenir, sonra canlı satır kalkar (aynı karede; titreme/yeniden beliriş yok). */
function kalici(who, text, fb){
  const L = LIVE[who];
  if(!ORIG_LINE){ if(L){ L.row.remove(); delete LIVE[who]; } return; }
  const finish = () => {
    const cur = LIVE[who];
    if(cur !== L && L){ return; }
    ORIG_LINE(who, text);
    const rows = document.querySelectorAll("#chat-log .sub." + who + ":not(.live)");
    const yeni = rows[rows.length - 1] || null;
    if(L){
      if(yeni) yeni.classList.add("ek-sabit");
      L.row.remove(); delete LIVE[who];
      const box = logBox(); altaKaydir(box, true);
    }
    RECENT[who] = {row: yeni, t: Date.now(), fb: !!fb};
  };
  if(L && L.text.length > L.shown){        // yazım henüz yetişmediyse önce hızla bitir, sonra değiştir (en çok ~0,7 sn)
    L.done = true; L.bitir = finish; pumpBaslat();
    setTimeout(() => { if(L.bitir){ const f = L.bitir; L.bitir = null; L.shown = L.text.length; L.node.nodeValue = L.text; f(); } }, 700);
  }else finish();
}
function ekCanli(who, text){
  if(who !== "ai" && who !== "you") return;
  text = String(text == null ? "" : text);
  if(!text.trim()) return;
  const L = canliSatir(who);
  if(!L) return;
  L.t = Date.now(); L.done = false; L.row.classList.remove("done");
  if(L.text !== text) canliYaz(L, text);
}
function ekCanliSon(who, override, prefix){
  if(prefix) PRE[who] = (PRE[who] || "") + String(prefix);
  const L = LIVE[who];
  if(!L) return;
  L.done = true; L.t = Date.now(); L.row.classList.add("done");
  if(override != null){                 // kesildi: yalnızca gerçekten konuşulan kalıcı olur
    kalici(who, String(override) || L.text, false);
  }else if(L.stash != null){
    kalici(who, L.stash, false);
  }
}
function norm(t){ return String(t || "").toLocaleLowerCase("tr").replace(/[^\p{L}\p{N}]+/gu, ""); }
function onekAt(who, text){
  const pre = PRE[who];
  if(!pre) return text;
  PRE[who] = "";
  const a = norm(pre), b = norm(text);
  if(!a || !b.startsWith(a)) return text;
  // gerçek metinde, ön ekin harf/rakamları bitene kadar ilerle
  let i = 0, j = 0;
  while(i < text.length && j < a.length){ if(norm(text[i])) j++; i++; }
  return text.slice(i).replace(/^[\s.,;:!?…\-–—]+/, "");
}
/* Gerçek satır geldiğinde: null → işlendi (özgün line çağrılmaz); yoksa özgün line'a verilecek metin. */
function canliSatiri(who, text){
  if(who !== "ai" && who !== "you") return text;
  text = onekAt(who, text);
  if(!String(text).trim()) return LIVE[who] && LIVE[who].done ? (kalici(who, LIVE[who].text, false), null) : null;
  const L = LIVE[who];
  if(L){
    if(who === "ai" && !L.done){ L.stash = text; return null; }       // ses bitmeden gerçek satır yazılmaz
    kalici(who, text, false); return null;
  }
  const R = RECENT[who];
  if(R && R.fb && R.row && R.row.isConnected && Date.now() - R.t < 120000){
    const n = R.row.firstChild;
    if(n && n.nodeType === 3){
      const a = norm(n.nodeValue), b = norm(text);
      if(a && b && (b.includes(a.slice(0, 14)) || a.includes(b.slice(0, 14)))){ n.nodeValue = text; delete RECENT[who]; return null; }
    }
  }
  return text;
}
setInterval(() => {                    // bekçi: Python'dan son iletinin gelmemesi durumunda canlı satır asılı kalmasın
  const now = Date.now();
  for(const who of Object.keys(LIVE)){
    const L = LIVE[who], yas = now - L.t;
    if(who === "you" ? yas > 6000 : ((L.done || L.stash != null) ? yas > (L.stash != null ? 25000 : 5000) : yas > 40000)){
      kalici(who, L.stash != null ? L.stash : L.text, L.stash == null);
    }
  }
}, 1000);

/* ---------------- Ekran oturumu: izin kartı + etkin oturum göstergesi ---------------- */
const EK = h("div", "ek-ekran"); EK.id = "ek-ekran"; EK.hidden = true;
document.body.appendChild(EK);
let ekSig = "", ekZaman = 0;
function ekranCiz(){
  const E = D && D.ekran;
  const imza = E ? JSON.stringify([!!E.acik, !!E.kontrol, E.istek ? [E.istek.kontrol, E.istek.dakika, E.istek.neden] : 0]) : "";
  const goster = !!(E && (E.acik || E.istek));
  if(!goster){ EK.hidden = true; EK.replaceChildren(); ekSig = ""; if(ekZaman){ clearInterval(ekZaman); ekZaman = 0; } return; }
  if(imza !== ekSig){
    ekSig = imza; EK.replaceChildren();
    if(E.istek){
      EK.dataset.mod = "istek";
      EK.appendChild(h("div", "ek-ekran-baslik", "BLOOM ekranına erişmek istiyor"));
      EK.appendChild(h("div", "ek-ekran-not", (E.istek.neden ? E.istek.neden + " · " : "") + Math.round(E.istek.dakika) + " dk · " +
        (E.istek.kontrol ? "tıklama ve klavye de isteniyor" : "yalnızca bakmak istiyor")));
      const sat = h("div", "ek-ekran-dugmeler");
      const dk = Math.round(E.istek.dakika);
      const bak = h("button", "ek-ekran-btn", "SADECE BAK"); bak.type = "button";
      bak.onclick = () => post("ek_ekran", {eylem: "izin", kontrol: false, dakika: dk});
      const kon = h("button", "ek-ekran-btn tehlike", "KONTROL VER"); kon.type = "button";
      kon.onclick = () => post("ek_ekran", {eylem: "izin", kontrol: true, dakika: dk});
      const red = h("button", "ek-ekran-btn gri", "REDDET"); red.type = "button";
      red.onclick = () => post("ek_ekran", {eylem: "reddet"});
      sat.append(bak, kon, red); EK.appendChild(sat);
      EK.appendChild(h("div", "ek-ekran-alt", "Karar sende: kontrol vermezsen BLOOM yalnızca ekranı görür. Süre dolunca kendiliğinden kapanır."));
    } else {
      EK.dataset.mod = E.kontrol ? "kontrol" : "bak";
      const sat = h("div", "ek-ekran-satir");
      sat.appendChild(h("i", "ek-ekran-nokta"));
      sat.appendChild(h("span", "ek-ekran-et", E.kontrol ? "EKRAN AÇIK · KONTROL" : "EKRAN AÇIK · BAKIYOR"));
      const sure = h("b", "ek-ekran-sure", ""); sure.id = "ek-ekran-sure"; sat.appendChild(sure);
      const dur = h("button", "ek-ekran-btn tehlike", "DURDUR"); dur.type = "button";
      dur.onclick = () => post("ek_ekran", {eylem: "durdur"});
      sat.appendChild(dur); EK.appendChild(sat);
      EK.appendChild(h("div", "ek-ekran-alt", "Acil durdurma: ESC tuşuna bas"));
    }
    EK.hidden = false;
  }
  if(!ekZaman) ekZaman = setInterval(ekranSure, 1000);
  ekranSure();
}
function ekranSure(){
  const E = D && D.ekran; if(!E) return;
  const el = $id("ek-ekran-sure");
  if(el && E.acik){ const k = Math.max(0, Math.round(E.bitis - Date.now() / 1000)); el.textContent = mmss(k); }
}

/* ---------------- Python → HUD ---------------- */
function install(){
  const J = window.jarvis;
  if(!J) return false;
  J.ekDurum = function(d){ D = d; paint(); schedule(); try{ ekranCiz(); }catch(e){} };
  if(!J.__ekLine){
    J.__ekLine = true;
    const orig = J.line;
    ORIG_LINE = function(who, text){ return orig.call(J, who, text); };
    J.line = function(who, text){ const t = canliSatiri(who, text); if(t == null) return; return orig.call(J, who, t); };
    J.ekCanli = ekCanli;
    J.ekCanliSon = ekCanliSon;
  }
  J.ekKaynaklar = showSources;
  J.ekPanelAc = function(t){ openPanel(t); };
  J.ekUyandi = uyandi;
  J.ekFikirYenile = fikirYenile;
  J.ekFikirAc = fikirAc;
  J.ekYetenekOnizle = function(r){ openPanel("yetenek"); if(r && r.anahtar_kaynak) R.ysUrl.value = r.anahtar_kaynak; ysGoster(r); };
  // Pomodoro evresi bitince HUD'un 30 sn çalan alarmı kısa kesilir (sesi 3,5 sn yeter).
  J.ekAlarm = function(){ setTimeout(() => { try{ if(typeof alarm === "function") alarm(false); }catch(e){} }, 3500); };
  return true;
}
function ready(){ if(install()) post("ek_hazir", {}); }
if(!install()) addEventListener("load", install);
if(window.pywebview && window.pywebview.api) ready();
addEventListener("pywebviewready", ready);

/* ---------------- çevrimdışı harita yedeği ----------------
   İnternet yoksa (ya da karo sunucusu cevap vermiyorsa) harita boş gri kalmasın: dünya ülkeleri + Türkiye illeri
   vektör olarak çizilir. Veri yalnızca gerektiğinde Python'dan istenir (ek_harita). */
let haritaVeri = null, haritaYukleniyor = false, haritalar = new Set();
function haritaVerisiniYukle(cb){
  if(haritaVeri) return cb(haritaVeri);
  if(window.__EK_HARITA){ haritaVeri = window.__EK_HARITA; return cb(haritaVeri); }
  if(haritaYukleniyor) return setTimeout(() => haritaVerisiniYukle(cb), 150);
  haritaYukleniyor = true;
  Promise.resolve(post("ek_harita", {})).then(txt => {
    haritaYukleniyor = false;
    try{ haritaVeri = typeof txt === "string" ? JSON.parse(txt) : txt; }catch(e){ haritaVeri = null; }
    if(haritaVeri) cb(haritaVeri);
  }).catch(() => { haritaYukleniyor = false; });
}
function haritaYedekle(map){
  if(map.__ekYedek || !window.L) return;
  map.__ekYedek = true;
  haritaVerisiniYukle(veri => {
    if(!veri) return;
    try{
      if(!map.getPane("ekbase")){ const p = map.createPane("ekbase"); p.style.zIndex = 150; p.style.pointerEvents = "none"; }
      const rend = L.canvas({pane: "ekbase", padding: 0.5});
      const ring = r => r.map(c => [c[1], c[0]]);
      const g = L.layerGroup();
      const sea = {renderer: rend, interactive: false, stroke: false, fill: false};
      g.addLayer(L.rectangle([[-90, -180], [90, 180]], Object.assign(sea, {fill: true, fillColor: "#0a1520", fillOpacity: 1})));
      for(const r of veri.d) g.addLayer(L.polygon(ring(r), {renderer: rend, interactive: false, color: "#3b6a80", weight: 0.8, fillColor: "#16283a", fillOpacity: 1}));
      for(const r of veri.t) g.addLayer(L.polygon(ring(r), {renderer: rend, interactive: false, color: "#4a8097", weight: 0.6, fillColor: "#1b3347", fillOpacity: 1}));
      g.addTo(map);
      map.__ekKatman = g;
      const note = h("div", "ek-offline", "ÇEVRİMDIŞI HARİTA · yalnızca ülke ve il sınırları");
      map.getContainer().appendChild(note);
    }catch(e){ console.error("ek harita", e); }
  });
}
if(window.L && L.Map && L.Map.addInitHook){
  L.Map.addInitHook(function(){
    const map = this;
    haritalar.add(map);
    if(navigator.onLine === false) setTimeout(() => haritaYedekle(map), 0);
    let ok = 0, err = 0;
    map.on("layeradd", ev => {
      const l = ev.layer;
      if(!l || !(l instanceof L.GridLayer)) return;
      l.on("tileload", () => { ok++; });
      l.on("tileerror", () => { err++; if(!ok && err >= 2) haritaYedekle(map); });
    });
  });
  addEventListener("offline", () => { for(const m of haritalar) haritaYedekle(m); });
}

/* KİŞİSEL KULLANIM: yapan/takip/yeni sürüm pencereleri hiçbir yoldan açılmasın (CSS de gizler; Python da artık çağırmaz) */
try{
  const kapali = () => {};
  if(typeof Follow !== "undefined") Follow.show = kapali;
  if(typeof Info !== "undefined") Info.open = kapali;
  if(typeof Update !== "undefined"){ Update.open = kapali; }
  if(typeof window.showTab === "function"){      // not: bu dosyanın kendi showTab'ı var; genel olan window.showTab
    const _showTab = window.showTab;
    window.showTab = function(name){ return _showTab(name === "hakkinda" ? "genel" : name); };   // "HATA" etiketi artık Genel'e açar
  }
}catch(e){}

/* ilk durum (Python hazır olmadan da düğme çizili olsun) */
paintTop();
})();
