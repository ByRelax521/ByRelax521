import { motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';

interface Arac { ad: string; aciklama: string }
interface Kategori { kategori: string; araclar: Arac[] }
interface Surum { surum: string; metin: string; ekran: string; arac: number }

const al = async <T,>(yol: string): Promise<T | null> => {
  try { const r = await fetch(yol, { cache: 'no-store' }); return r.ok ? await r.json() as T : null; } catch { return null; }
};

/** LOG: sürüm, yapabildiği her şey (kayıtlı araçlardan, güncel) ve günlük. Veri ek_web'den (yerel) gelir. */
export default function LogPanel({ onClose }: { onClose(): void }) {
  const [sekme, setSekme] = useState<'ozellik' | 'gunluk'>('ozellik');
  const [surum, setSurum] = useState<Surum | null>(null);
  const [kat, setKat] = useState<Kategori[] | null>(null);
  const [komutlar, setKomutlar] = useState<string[][]>([]);
  const [satirlar, setSatirlar] = useState<string[] | null>(null);
  const [ara, setAra] = useState('');
  const [hata, setHata] = useState(false);
  const [kopya, setKopya] = useState(false);
  const liste = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let iptal = false;
    (async () => {
      const [s, o] = await Promise.all([al<Surum>('/api/surum'), al<{ kategoriler: Kategori[]; komutlar: string[][] }>('/api/ozellikler')]);
      if (iptal) return;
      setSurum(s); setKat(o?.kategoriler ?? null); setKomutlar(o?.komutlar ?? []); setHata(!s && !o);
    })();
    return () => { iptal = true; };
  }, []);

  useEffect(() => {
    if (sekme !== 'gunluk') return;
    let iptal = false; let t = 0;
    const yukle = async () => {
      const d = await al<{ satirlar: string[] }>('/api/log?n=400');
      if (iptal) return;
      setSatirlar(d?.satirlar ?? null);
      t = window.setTimeout(yukle, 3000);
    };
    yukle();
    return () => { iptal = true; clearTimeout(t); };
  }, [sekme]);

  // günlük açıkken en alta yapış (kullanıcı yukarı kaydırmadıysa)
  useEffect(() => {
    const e = liste.current; if (!e || sekme !== 'gunluk') return;
    if (e.scrollHeight - e.scrollTop - e.clientHeight < 80) e.scrollTop = e.scrollHeight;
  }, [satirlar, sekme]);

  const q = ara.trim().toLocaleLowerCase('tr');
  const sat = (satirlar ?? []).filter(s => !q || s.toLocaleLowerCase('tr').includes(q));
  const katF = (kat ?? []).map(k => ({ ...k, araclar: k.araclar.filter(a => !q || a.ad.includes(q) || a.aciklama.toLocaleLowerCase('tr').includes(q)) })).filter(k => k.araclar.length);
  const kopyala = async () => {
    const metin = sekme === 'gunluk' ? sat.join('\n') : katF.map(k => k.kategori.toUpperCase() + '\n' + k.araclar.map(a => `  ${a.ad} — ${a.aciklama}`).join('\n')).join('\n\n');
    try { await navigator.clipboard.writeText(metin); setKopya(true); setTimeout(() => setKopya(false), 1500); } catch { /* pano izni yok */ }
  };

  return (
    <motion.aside className="bl-hist bl-log" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 30 }} transition={{ duration: 0.25 }}>
      <header>
        <b>LOG{surum ? ` · BLOOM ${surum.surum}` : ''}</b>
        <button onClick={onClose} aria-label="Kapat">✕</button>
      </header>
      <nav className="bl-tabs">
        <button className={sekme === 'ozellik' ? 'on' : ''} onClick={() => setSekme('ozellik')}>YAPABİLDİKLERİM{surum ? ` (${surum.arac})` : ''}</button>
        <button className={sekme === 'gunluk' ? 'on' : ''} onClick={() => setSekme('gunluk')}>GÜNLÜK</button>
      </nav>
      <div className="bl-tools">
        <input value={ara} onChange={e => setAra(e.target.value)} placeholder={sekme === 'gunluk' ? 'Günlükte ara…' : 'Özellik ara…'} aria-label="Ara" />
        <button onClick={kopyala}>{kopya ? 'KOPYALANDI' : 'KOPYALA'}</button>
      </div>
      <div className="bl-hist-list bl-log-list" ref={liste}>
        {hata && <p className="dim">Bilgi alınamadı (yerel hizmete ulaşılamıyor).</p>}
        {sekme === 'ozellik' && (
          <>
            {surum && <pre className="bl-sur">{surum.metin}</pre>}
            {katF.map(k => (
              <section key={k.kategori} className="bl-kat">
                <h4>{k.kategori}</h4>
                {k.araclar.map(a => <p key={a.ad}><code>{a.ad}</code> {a.aciklama}</p>)}
              </section>
            ))}
            {kat && !katF.length && <p className="dim">Eşleşen özellik yok.</p>}
            {komutlar.length > 0 && (
              <section className="bl-kat">
                <h4>Yazı kutusu komutları</h4>
                {komutlar.map(([c, d]) => <p key={c}><code>{c}</code> {d}</p>)}
              </section>
            )}
          </>
        )}
        {sekme === 'gunluk' && (
          <>
            {satirlar === null && !hata && <p className="dim">Yükleniyor…</p>}
            {sat.map((s, i) => <p key={i} className={'bl-gl' + (/hata|error|traceback|exception/i.test(s) ? ' e' : '')}>{s}</p>)}
          </>
        )}
      </div>
    </motion.aside>
  );
}
