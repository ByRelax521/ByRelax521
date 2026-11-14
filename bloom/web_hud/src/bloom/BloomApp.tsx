import { AnimatePresence, motion } from 'framer-motion';
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import type { Dashboard } from '../lib/types';
import type { Kontrol } from '../hands/controller';
import BloomMark2 from './BloomMark2';
import LogPanel from './LogPanel';
import { cagri, seviyeOku, ust, useBloom } from './store';

const HandControl = lazy(() => import('../hands/HandControl'));

async function panoAl(): Promise<Dashboard | null> {
  try { const r = await fetch('/api/dashboard', { cache: 'no-store' }); return r.ok ? await r.json() : null; } catch { return null; }
}

export default function BloomApp() {
  const st = useBloom();
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [denendi, setDenendi] = useState(false);
  const [input, setInput] = useState('');
  const [gecmis, setGecmis] = useState(false);
  const [logAcik, setLogAcik] = useState(false);
  const [el, setEl] = useState(false);
  const [introAt] = useState(() => Date.now());
  const stRef = useRef(st); stRef.current = st;

  // Pano: açılışta, sonra 5 dakikada bir (sunucu kendi önbelleğini tutar). Başarısızsa 30 sn sonra yeniden.
  useEffect(() => {
    let kapali = false; let t = 0;
    const yukle = async () => {
      const d = await panoAl();
      if (kapali) return;
      setDash(prev => d ?? prev); setDenendi(true);
      t = window.setTimeout(yukle, d ? 300_000 : 30_000);
    };
    yukle();
    return () => { kapali = true; clearTimeout(t); };
  }, []);

  // Çekirdek: mikrofon düzeyi; konuşurken Python düzey vermez (yalnız giriş), hafif dalga ver
  const level = useCallback(() => {
    const s = stRef.current; const g = seviyeOku();
    if (s.core === 'speaking') return Math.max(g, 0.28 + 0.22 * Math.sin(performance.now() / 140) + 0.12 * Math.sin(performance.now() / 53));
    return g;
  }, []);

  const gonder = (t: string) => { const m = t.trim(); if (!m) return;
    cagri('line', ['you', m]);   // yazılan satırı Python geri yollamaz (klasik HUD kendi ekler): geçmişe biz ekleriz
    ust('metin', { text: m }); setInput(''); };
  const eylem = (k: Kontrol) => {
    const e = k.eylem;
    if (e.tip === 'komut') gonder(e.metin);
    else if (e.tip === 'sustur') ust('mic');
  };

  // Kısayollar: H el kontrolü
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.code === 'KeyH' && !e.repeat && !e.ctrlKey && !e.metaKey && !e.altKey) setEl(v => !v);
      if (e.code === 'Escape') { setGecmis(false); setLogAcik(false); setEl(false); }
    };
    window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f);
  }, []);

  const caption = st.core === 'speaking' ? st.canli.ai : st.core === 'listening' ? st.canli.you : '';
  if (el) {
    return (
      <Suspense fallback={null}>
        <HandControl caption={caption} core={st.core} onAction={eylem} onClose={() => setEl(false)} userName="" />
      </Suspense>
    );
  }
  return (
    <BloomMark2
      st={st} dash={dash} dashDenendi={denendi} level={level} introAt={introAt}
      input={input} setInput={setInput} onSubmit={gonder}
      onMic={() => ust('mic')} onCam={() => ust('cam')} onHands={() => setEl(true)} onSleep={() => ust('uyku')}
      onSettings={() => ust('ayarlar')} onPanel={() => ust('panel')} onModel={() => ust('model')}
      onHistory={() => { setGecmis(g => !g); setLogAcik(false); }} historyOpen={gecmis}
      onLog={() => { setLogAcik(v => !v); setGecmis(false); }} logOpen={logAcik}
      overlay={
        <AnimatePresence>
          {logAcik && <LogPanel key="log" onClose={() => setLogAcik(false)} />}
          {gecmis && (
            <motion.aside className="bl-hist" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }} transition={{ duration: 0.25 }}>
              <header><b>SOHBET GEÇMİŞİ</b><button onClick={() => setGecmis(false)} aria-label="Kapat">✕</button></header>
              <div className="bl-hist-list">
                {st.satirlar.length === 0 && <p className="dim">Henüz konuşma yok.</p>}
                {st.satirlar.map(s => (
                  <p key={s.id} className={'bl-l ' + s.who}><i>{s.who === 'you' ? 'SİZ' : s.who === 'ai' ? 'BLOOM' : s.who === 'error' ? 'HATA' : 'SİSTEM'}</i> {s.text}</p>
                ))}
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
      }
    />
  );
}
