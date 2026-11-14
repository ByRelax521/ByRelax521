/* BLOOM Mark 2 — görünüm katmanı. Özgün HUD olduğu gibi çalışır; bu betik yalnızca sınıf, çip ve ikon düğmeleri ekler.
   Kapat/aç: Ctrl+Shift+M (tercih bu cihazda saklanır). */
(function(){
  if(window.__bloomM2) return; window.__bloomM2 = true;
  var KEY = 'bloom_m2', body = document.body;
  function on(){ try{ return localStorage.getItem(KEY) !== '0'; }catch(e){ return true; } }
  function set(v){ try{ localStorage.setItem(KEY, v ? '1' : '0'); }catch(e){} body.classList.toggle('m2', v); }
  var ICON = {
    mic: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    cam: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3"/></svg>',
    send: '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
  };
  function el(tag, attrs, html){ var e = document.createElement(tag); for(var k in (attrs||{})) e.setAttribute(k, attrs[k]); if(html != null) e.innerHTML = html; return e; }
  function gonder(metin){
    var c = document.getElementById('cmd'); if(!c || c.disabled) return;
    c.value = metin; c.dispatchEvent(new Event('input', {bubbles:true}));
    c.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
  }
  var CIPLER = ['Bugün ne var?', 'Hava nasıl?', 'Pomodoro başlat', 'Bir not al', 'Müzik aç'];
  function kur(){
    if(document.getElementById('m2-chips')) return;
    body.appendChild(el('div', {id:'m2-status'}, ''));
    body.appendChild(el('div', {id:'m2-hint'}, 'Mikrofona dokun ya da yaz.'));
    var cips = el('div', {id:'m2-chips'});
    CIPLER.forEach(function(t){
      var b = el('button', {type:'button'}); b.textContent = t;
      b.onclick = function(){ if(t === 'Bir not al'){ var c = document.getElementById('cmd'); if(c){ c.focus(); c.value = 'Not al: '; } } else gonder(t); };
      cips.appendChild(b);
    });
    body.appendChild(cips);
    // alt çubuğa mikrofon ve kamera ikon düğmeleri: üstteki gerçek düğmelere vekâlet eder (durumu aynalar)
    var bar = document.getElementById('bar');
    if(bar && !bar.querySelector('.m2-ib')){
      function vekil(id, cls, ikon, baslik){
        var b = el('button', {type:'button', 'class':'m2-ib ' + cls, title:baslik, 'aria-label':baslik}, ikon);
        b.onclick = function(){ var t = document.getElementById(id); if(t) t.click(); };
        bar.appendChild(b);
        var kaynak = document.getElementById(id);
        function esle(){ if(kaynak) b.dataset.on = kaynak.dataset.on || '1'; }
        if(kaynak){ new MutationObserver(esle).observe(kaynak, {attributes:true, attributeFilter:['data-on']}); esle(); }
      }
      vekil('t-cam', 'cam', ICON.cam, 'Kamerayı aç/kapat');
      vekil('t-mic', 'mic', ICON.mic, 'Mikrofonu aç/kapat');
    }
    // durum yazısı üstteki durum çipini aynalar
    var st = document.getElementById('t-state'), ms = document.getElementById('m2-status');
    function dur(){ if(st && ms) ms.textContent = st.textContent; }
    if(st){ new MutationObserver(dur).observe(st, {childList:true, characterData:true, subtree:true}); dur(); }
    // sohbet başlayınca çipler çekilir
    var log = document.getElementById('chat-log');
    function sohbet(){ body.classList.toggle('m2-sohbet', !!(log && log.children.length)); }
    if(log){ new MutationObserver(sohbet).observe(log, {childList:true}); sohbet(); }
  }
  kur(); set(on());
  window.addEventListener('keydown', function(e){
    if(e.ctrlKey && e.shiftKey && (e.key === 'M' || e.key === 'm')){ e.preventDefault(); set(!body.classList.contains('m2')); }
  }, true);
  window.bloomM2 = {ac: function(){ set(true); }, kapat: function(){ set(false); }, durum: function(){ return body.classList.contains('m2'); }};
})();
