// BLOOM köprüsü: HUD sayfası (ana pencere) Python'dan gelen çağrıları iframe'e postMessage ile aktarır.
// Bu dosya o iletileri küçük bir depoda toplar; arayüz depodan okur. Python'a dönüş yine postMessage (üst sayfa yürütür).
import { useSyncExternalStore } from 'react';
import type { CoreState } from '../lib/types';

export interface Satir { id: number; who: 'you' | 'ai' | 'sys' | 'error'; text: string; at: number }
export interface Panel { key: string; label?: string; kind?: string; value?: string; unit?: string; items?: { a?: string; b?: string; past?: boolean; late?: boolean }[]; rows?: string[][]; ratio?: number; hint?: string; lat?: number; lon?: number; place?: string; detail?: string; state?: string; next?: string }
export interface EkDurum { pomo?: { aktif?: boolean; faz?: string; etiket?: string; gorev?: string; biter?: number; kalan?: number | null; duraklat?: boolean; sira?: number; tur?: number }; yayin?: { acik?: boolean }; [k: string]: unknown }

export interface BloomState {
  hazir: boolean;                 // üst sayfadan en az bir ileti geldi
  durum: string;                  // connecting | listening | thinking | speaking | idle | paused | error | asleep
  etiket: string;                 // Python'un verdiği kısa neden (hata için)
  core: CoreState;
  satirlar: Satir[];
  canli: { you: string; ai: string };
  adimlar: string[];              // araç günlüğü
  paneller: Record<string, Panel>;
  ek: EkDurum;
  mikAcik: boolean;
  kamAcik: boolean;
  yayin: boolean;
  surum: number;
}

const ilk: BloomState = {
  hazir: false, durum: 'connecting', etiket: '', core: 'idle', satirlar: [], canli: { you: '', ai: '' }, adimlar: [], paneller: {}, ek: {},
  mikAcik: true, kamAcik: false, yayin: false, surum: 0,
};

let S: BloomState = ilk;
const dinleyen = new Set<() => void>();
let n = 0;
const yay = (p: Partial<BloomState>) => { S = { ...S, ...p, surum: S.surum + 1 }; dinleyen.forEach(f => f()); };

const CORE: Record<string, CoreState> = { listening: 'listening', thinking: 'thinking', speaking: 'speaking' };
let seviye = 0;
/** Mikrofon/ses düzeyi (0..1); çekirdek her karede okur */
export const seviyeOku = () => seviye;

/** Üst sayfa → iframe: Python'un HUD'a yaptığı çağrılar (jarvis.state, jarvis.line ...) */
export function cagri(fn: string, a: unknown[]): void {
  const x = a[0] as Record<string, unknown> | string | number | undefined;
  switch (fn) {
    case 'state': {
      const d = String(x ?? 'idle');
      yay({ hazir: true, durum: d, etiket: String(a[1] ?? ''), core: CORE[d] ?? 'idle' });
      break;
    }
    case 'line': {
      const who = String(x) as Satir['who'];
      const text = String(a[1] ?? '');
      if (!text.trim()) break;
      const k = who === 'you' || who === 'ai' ? who : null;
      yay({ hazir: true, satirlar: [...S.satirlar, { id: ++n, who, text, at: Date.now() }].slice(-60), canli: k ? { ...S.canli, [k]: '' } : S.canli });
      break;
    }
    case 'ekCanli': {
      const who = String(x); const text = String(a[1] ?? '');
      if (who === 'you' || who === 'ai') yay({ canli: { ...S.canli, [who]: text } });
      break;
    }
    case 'tool': {
      const ad = String(x); const ok = a[1] !== false; const ozet = String(a[2] ?? '');
      yay({ adimlar: [...S.adimlar, `${ad}${ozet ? ' · ' + ozet : ''}${ok ? '' : ' ✗'}`].slice(-12) });
      break;
    }
    case 'level': seviye = Math.max(0, Math.min(1, Math.sqrt(Number(x) || 0) * 2.6)); break;
    case 'panel': { const p = x as unknown as Panel | null; if (p && p.key) yay({ paneller: { ...S.paneller, [p.key]: p } }); break; }
    case 'panels': { const l = (x as unknown as Panel[]) || []; const m: Record<string, Panel> = {}; for (const p of l) if (p && p.key) m[p.key] = p; yay({ paneller: m }); break; }
    case 'ekDurum': { const d = (x as unknown as EkDurum) || {}; yay({ ek: d, yayin: !!(d.yayin as { acik?: boolean } | undefined)?.acik }); break; }
    case 'mic': yay({ mikAcik: !!x }); break;
    case 'cam': yay({ kamAcik: !!x }); break;
    case 'sleep': { const on = !!x; yay(on ? { durum: 'asleep', core: 'idle' } : S.durum === 'asleep' ? { durum: 'idle', core: 'idle' } : {}); break; }
    case 'hazir': yay({ hazir: true }); break;
    default: break;
  }
}

export function abone(f: () => void) { dinleyen.add(f); return () => { dinleyen.delete(f); }; }
export const al = () => S;
export const useBloom = () => useSyncExternalStore(abone, al);

// ---------------------------------------------------------------- iframe → üst sayfa
export const cerceve = typeof window !== 'undefined' && window.parent !== window;
/** Çerçevesiz (geliştirme/test) çalışmada gönderilenler */
export const bagimsiz: [string, Record<string, unknown>][] = [];
/** Üst sayfaya komut: mic | cam | uyku | ayarlar | panel | model | metin */
export function ust(act: string, data: Record<string, unknown> = {}): void {
  if (cerceve) window.parent.postMessage({ bloom: 'ui', act, ...data }, '*');
  else bagimsiz.push([act, data]);
}

if (typeof window !== 'undefined') {
  window.addEventListener('message', e => {
    const m = e.data as { bloom?: string; fn?: string; args?: unknown[] } | null;
    if (m && m.bloom === 'call' && typeof m.fn === 'string') cagri(m.fn, m.args || []);
  });
  // F4/F6/Esc: odak çerçevedeyken de HUD kısayolları çalışsın
  window.addEventListener('keydown', e => {
    if (cerceve && e.ctrlKey && e.shiftKey && (e.key === 'W' || e.key === 'w')) { e.preventDefault(); ust('kapat'); return; }
    if (!cerceve || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'F4' || e.key === 'F6') { e.preventDefault(); ust('tus', { key: e.key }); }
  });
  // test/geliştirme kancası
  (window as unknown as { __bloom: unknown }).__bloom = { cagri, al, bagimsiz };
  if (cerceve) window.parent.postMessage({ bloom: 'hazir' }, '*');
}
