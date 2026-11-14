/* BLOOM Mark 2 web ekranı: jarvis-main arayüzü, yerel hizmetten (ek_web) bir iframe içinde açılır.
   HUD sayfası "ev sahibi"dir: Python'un jarvis.* çağrılarını iframe'e iletir, iframe'in komutlarını gerçek HUD düğmelerine çevirir.
   Ses/mikrofon/kamera Python'dadır. iframe 6 sn içinde "hazir" demezse (hizmet yok, dosya eksik) kendini kaldırır → Mark 2 katmanı kalır.
   Aç/kapat: Ctrl+Shift+W (tercih bu cihazda: localStorage bloom_web). */
(function(){
  if(window.__bloomWeb) return; window.__bloomWeb = true;
  var KEY = 'bloom_web', body = document.body, fr = null, hazir = false, url = '', zamanasimi = 0;
  var IL = ['state','line','tool','level','panel','panels','ekDurum','ekCanli','mic','webcam','sleep'];
  var son = {state:null, ekDurum:null, panels:{}, satirlar:[], mic:null, cam:null, sleep:null, canli:{you:'',ai:''}};
  function acik(){ try{ return localStorage.getItem(KEY) !== '0'; }catch(e){ return true; } }
  function yaz(v){ try{ localStorage.setItem(KEY, v ? '1' : '0'); }catch(e){} }
  function gonder(fn, args){
    if(!fr || !hazir || !fr.contentWindow) return;
    try{ fr.contentWindow.postMessage({bloom:'call', fn:fn, args:args}, '*'); }catch(e){}
  }
  // ---- Python → HUD çağrılarını yakala (özgün işlev önce çalışır; hata ona zarar vermez)
  function not(fn, a){
    if(fn === 'state') son.state = a;
    else if(fn === 'ekDurum') son.ekDurum = a;
    else if(fn === 'panel'){ var p = a[0]; if(p && p.key) son.panels[p.key] = p; }
    else if(fn === 'panels'){ var m = {}; (a[0] || []).forEach(function(p){ if(p && p.key) m[p.key] = p; }); son.panels = m; }
    else if(fn === 'line'){ son.satirlar.push(a); if(son.satirlar.length > 60) son.satirlar.shift(); if(a[0] === 'you' || a[0] === 'ai') son.canli[a[0]] = ''; }
    else if(fn === 'ekCanli'){ if(a[0] === 'you' || a[0] === 'ai') son.canli[a[0]] = a[1]; }
    else if(fn === 'webcam') fn = 'cam', a = [a[0]], son.cam = a[0];
    else if(fn === 'mic') son.mic = a[0];
    else if(fn === 'sleep') son.sleep = a[0];
    gonder(fn, a);
  }
  var gir = {};
  function sar(){
    var J = window.jarvis; if(!J) return;
    IL.forEach(function(n){
      var o = J[n];
      if(typeof o !== 'function' || o.__bw) return;
      var w = function(){
        // jarvis-ek.js sonradan J.line'ı yeniden sarabilir: iç içe sarmalayıcılar aynı çağrıyı bir kez bildirsin
        var dis = !gir[n]; gir[n] = (gir[n] || 0) + 1; var r;
        try{ r = o.apply(this, arguments); }finally{ gir[n]--; if(dis){ try{ not(n, Array.prototype.slice.call(arguments)); }catch(e){} } }
        return r;
      };
      w.__bw = true; J[n] = w;
    });
  }
  setInterval(sar, 400); sar();
  // ---- kullanıcının yaptığı değişiklikler (düğme/kısayol) jarvis.* çağırmaz: DOM'dan izle
  function izle(id, isle){
    var e = document.getElementById(id); if(!e) return;
    new MutationObserver(isle).observe(e, {attributes:true, attributeFilter:['data-on']});
  }
  function izleAll(){
    izle('t-mic', function(){ var v = document.getElementById('t-mic').dataset.on !== '0'; son.mic = v; gonder('mic', [v]); });
    izle('t-cam', function(){ var v = document.getElementById('t-cam').dataset.on === '1'; son.cam = v; gonder('cam', [v]); });
    new MutationObserver(function(){ var v = body.dataset.sleep === '1'; son.sleep = v; gonder('sleep', [v]); }).observe(body, {attributes:true, attributeFilter:['data-sleep']});
  }
  // ---- iframe → HUD
  function tikla(id){ var e = document.getElementById(id); if(e) e.click(); }
  function komut(d){
    var c = document.getElementById('cmd');
    switch(d.act){
      case 'mic': tikla('t-mic'); break;
      case 'cam': tikla('t-cam'); break;
      case 'ayarlar': tikla('t-settings'); break;
      case 'model': tikla('t-persona'); break;
      case 'panel': if(window.jarvis && window.jarvis.ekPanelAc) window.jarvis.ekPanelAc('odak'); break;
      case 'uyku': if(typeof setSleep === 'function') setSleep(body.dataset.sleep !== '1'); break;
      case 'metin':
        if(!c || c.disabled || !String(d.text || '').trim()) break;
        c.value = String(d.text).slice(0, 4000); c.dispatchEvent(new Event('input', {bubbles:true}));
        c.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
        break;
      case 'tus':
        document.dispatchEvent(new KeyboardEvent('keydown', {key:d.key, bubbles:true})); window.dispatchEvent(new KeyboardEvent('keydown', {key:d.key, bubbles:true})); break;
      case 'kapat': kapat(true); break;
    }
  }
  function durumOku(){
    // betik, Python'un ilk state çağrısından sonra yüklenmiş olabilir: durumu HUD'un kendi etiketinden çıkar
    try{
      var t = document.getElementById('t-state'), txt = t && t.textContent.trim();
      if(typeof LABEL === 'object' && txt) for(var k in LABEL) if(LABEL[k] === txt) return k !== 'asleep' ? [k, ''] : null;
    }catch(e){}
    return null;
  }
  function tekrar(){
    if(!son.state) son.state = durumOku();
    if(son.state) gonder('state', son.state);
    if(son.sleep === null && body.dataset.sleep === '1') son.sleep = true;
    if(son.sleep !== null) gonder('sleep', [son.sleep]);
    var ps = Object.keys(son.panels).map(function(k){ return son.panels[k]; });
    if(ps.length) gonder('panels', [ps]);
    if(son.ekDurum) gonder('ekDurum', son.ekDurum);
    son.satirlar.forEach(function(a){ gonder('line', a); });
    if(son.mic !== null) gonder('mic', [son.mic]); else { var t = document.getElementById('t-mic'); if(t) gonder('mic', [t.dataset.on !== '0']); }
    if(son.cam !== null) gonder('cam', [son.cam]);
    ['you','ai'].forEach(function(k){ if(son.canli[k]) gonder('ekCanli', [k, son.canli[k]]); });
    gonder('hazir', []);
  }
  window.addEventListener('message', function(e){
    if(!fr || e.source !== fr.contentWindow) return;
    var d = e.data; if(!d || typeof d !== 'object') return;
    if(d.bloom === 'hazir'){ hazir = true; clearTimeout(zamanasimi); body.classList.add('bw'); tekrar(); }
    else if(d.bloom === 'ui') komut(d);
  });
  function kur(){
    if(fr || !url) return;
    fr = document.createElement('iframe'); fr.id = 'bw-frame'; fr.src = url; fr.title = 'BLOOM';
    fr.setAttribute('allow', 'camera; microphone; fullscreen');
    document.body.appendChild(fr);
    zamanasimi = setTimeout(function(){ if(!hazir){ kapat(false); try{ console.warn('bloom-web: ekran 6 sn içinde açılmadı; Mark 2 katmanı gösteriliyor'); }catch(e){} } }, 6000);
  }
  function kapat(kalici){
    clearTimeout(zamanasimi);
    if(fr){ fr.remove(); fr = null; }
    hazir = false; body.classList.remove('bw'); if(kalici) yaz(false);
  }
  function ac(){
    yaz(true);
    if(url){ kur(); return; }
    var p; try{ p = window.pywebview && window.pywebview.api && window.pywebview.api.post('ek_web_adres', {}); }catch(e){}
    if(p && p.then) p.then(function(u){ if(u && typeof u === 'string'){ url = u; if(acik()) kur(); } }).catch(function(){});
  }
  izleAll();
  window.addEventListener('keydown', function(e){
    if(e.ctrlKey && e.shiftKey && (e.key === 'W' || e.key === 'w')){ e.preventDefault(); if(fr) kapat(true); else ac(); }
  }, true);
  window.bloomWeb = {ac: ac, kapat: function(){ kapat(true); }, durum: function(){ return !!(fr && hazir); }, son: son};
  if(acik()) ac();
})();
