// BLOOM'un ana ekranı: jarvis-main'in Mark 2 yoğun HUD'u (halilozat/jarvis, MIT) BLOOM verisiyle.
// Orb, halkalar, küre, hava kadranı, haber, sistem kutuları aynı bileşenler; veri BLOOM'dan (Python) gelir.
import { AnimatePresence, motion } from 'framer-motion';
import { useMemo, type ReactNode } from 'react';
import { cityCoord } from '../data/cities';
import type { CoreState, Dashboard } from '../lib/types';
import { Globe, type GlobeMarker } from '../mark2/Globe';
import { HudCore } from '../mark2/HudCore';
import { Orbit } from '../mark2/Orbit';
import { Box, DateDial, DayRuler, RingGauge, RoundButton, Row, WeatherDial } from '../mark2/parts';
import { pad2, useClientStats, useNow } from '../mark2/stats';
import type { BloomState, Panel } from './store';
import '../mark2/mark2.css';
import './bloom.css';

export interface Props {
  st: BloomState;
  dash: Dashboard | null;
  dashDenendi: boolean;
  level: () => number;
  introAt: number | null;
  input: string;
  setInput(s: string): void;
  onSubmit(text: string): void;
  onMic(): void;
  onCam(): void;
  onHands(): void;
  onSleep(): void;
  onSettings(): void;
  onPanel(): void;
  onModel(): void;
  onHistory(): void;
  onLog(): void;
  logOpen: boolean;
  historyOpen: boolean;
  overlay?: ReactNode;
}

const ETIKET: Record<string, string> = {
  connecting: 'BAĞLANIYOR', listening: 'DİNLİYOR', thinking: 'DÜŞÜNÜYOR', speaking: 'KONUŞUYOR', idle: 'HAZIR',
  paused: 'SESSİZ', error: 'HATA', asleep: 'UYKUDA',
};

const hhmm = (iso: string) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };

/** "%41" / "%62 dolu" / "%80 · şarjda" → 0..1 */
const yuzde = (s: string | undefined): number | null => { const m = /(\d+(?:[.,]\d+)?)\s*%|%\s*(\d+(?:[.,]\d+)?)/.exec(s ?? ''); const v = m ? Number((m[1] ?? m[2]).replace(',', '.')) : NaN; return Number.isFinite(v) ? v / 100 : null; };
const ton = (f: number | null, ters = false): 'ok' | 'warn' | 'bad' | 'dim' => (f === null ? 'dim' : (ters ? 1 - f : f) > 0.9 ? 'bad' : (ters ? 1 - f : f) > 0.75 ? 'warn' : 'ok');

function kaynak(panel: Panel | undefined, st: BloomState) {
  const rows = panel?.rows ?? [];
  const get = (k: string) => rows.find(r => r[0] === k)?.[1];
  const pil = get('PİL');
  const cpu = panel?.value ? Number(panel.value) / 100 : null;
  void st;
  return { cpu: cpu !== null && Number.isFinite(cpu) ? cpu : null, ram: get('RAM'), disk: get('DİSK'), pil };
}

export default function BloomMark2(p: Props) {
  const { st, dash } = p;
  const now = useNow(60_000);
  const cs = useClientStats();
  const sys = kaynak(st.paneller.system, st);
  const w = dash?.weather ?? null;
  const src = dash?.news;
  const harita = st.paneller.map;

  // Küre: BLOOM'un harita paneli ya da hava şehri
  const noktalar: GlobeMarker[] = useMemo(() => {
    const m: GlobeMarker[] = [];
    if (harita && typeof harita.lat === 'number' && typeof harita.lon === 'number') m.push({ lon: harita.lon, lat: harita.lat, label: harita.place || 'KONUM', hot: true });
    return m;
  }, [harita]);
  const ev: [number, number] | null = w ? (typeof w.lon === 'number' && typeof w.lat === 'number' ? [w.lon, w.lat] : cityCoord(w.city)) : null;
  const markers: GlobeMarker[] = noktalar.length ? noktalar : ev ? [{ lon: ev[0], lat: ev[1], label: w!.city }] : [];
  const odak: [number, number] | null = noktalar.length ? [noktalar[0].lon, noktalar[0].lat] : null;

  // Altyazı: canlı satır → son söz
  const son = [...st.satirlar].reverse().find(s => s.who === 'you' || s.who === 'ai');
  const canli = st.core === 'listening' ? st.canli.you : st.core === 'speaking' ? st.canli.ai : '';
  const yeni = son && Date.now() - son.at < 20_000;
  const caption = canli || (st.core === 'listening' ? 'dinliyorum…' : st.durum === 'error' && st.etiket ? st.etiket : yeni && son ? son.text : '');
  const who = canli ? (st.core === 'listening' ? 'SİZ' : 'BLOOM') : st.core === 'listening' ? 'SİZ' : son?.who === 'you' ? 'SİZ' : 'BLOOM';
  const durumYazi = st.durum === 'error' && st.etiket ? `HATA · ${st.etiket.toLocaleUpperCase('tr')}` : ETIKET[st.durum] ?? st.durum.toUpperCase();

  const takvim = [st.paneller.calendar, st.paneller.reminders].flatMap(pn => (pn?.items ?? []).map(i => ({ a: i.a ?? '', b: i.b ?? '', gecti: !!i.past, gec: !!i.late })));
  const takvimIpucu = [st.paneller.calendar, st.paneller.reminders].map(pn => pn?.hint).find(Boolean);
  const pomo = st.ek.pomo;
  const pomoYazi = pomo && pomo.aktif ? `${pomo.etiket ?? 'POMODORO'}${pomo.gorev ? ' · ' + pomo.gorev : ''}` : '';

  const pilFrac = cs.battery ?? yuzde(sys.pil);
  const cpuTon: 'ok' | 'warn' | 'bad' = ton(sys.cpu) === 'bad' ? 'bad' : ton(sys.cpu) === 'warn' ? 'warn' : 'ok';
  const core: CoreState = st.core;
  const dim = core === 'thinking';

  return (
    <div className={`mk2 bloom m2-state-${core}${st.durum === 'asleep' ? ' uykuda' : ''}`}>
      <div className="m2-bg"><div className="m2-grid" /><div className="m2-rings-bg" /><div className="m2-vig" /></div>

      <header className="m2-top">
        <DayRuler day={now.getDate()} month={now.getMonth()} year={now.getFullYear()} />
        <div className="m2-top-r">
          <span className={'m2-link ' + (st.hazir && st.durum !== 'connecting' && st.durum !== 'error' ? 'on' : 'off')}>{st.hazir && st.durum !== 'connecting' && st.durum !== 'error' ? 'BAĞLI' : st.durum === 'error' ? 'HATA' : 'BAĞLANIYOR'}</span>
          {st.yayin && <span className="m2-demo">YAYIN</span>}
          <button type="button" className={'m2-logbtn' + (p.logOpen ? ' on' : '')} onClick={p.onLog} title="Sürüm, yapabildiklerim ve günlük">LOG</button>
          <span className="m2-brain">BEYİN · GEMİNİ LIVE</span>
        </div>
      </header>

      <aside className="m2-left">
        <DateDial />
        <Box title="SİSTEM" meta="BU BİLGİSAYAR">
          <Row k="işlemci" v={sys.cpu === null ? '—' : `%${Math.round(sys.cpu * 100)}`} frac={sys.cpu} tone={ton(sys.cpu)} />
          <Row k="bellek" v={sys.ram ?? '—'} frac={yuzde(sys.ram)} tone={ton(yuzde(sys.ram))} />
          <Row k="disk" v={sys.disk ?? '—'} frac={yuzde(sys.disk)} tone={ton(yuzde(sys.disk))} />
          <Row k="mikrofon" v={st.mikAcik ? (st.durum === 'paused' ? 'sessiz' : 'açık') : 'kapalı'} tone={st.mikAcik ? 'ok' : 'dim'} frac={st.mikAcik ? 1 : 0} />
          <Row k="kamera" v={st.kamAcik ? 'açık' : 'kapalı'} tone={st.kamAcik ? 'ok' : 'dim'} frac={st.kamAcik ? 1 : 0} />
          <Row k="haberler" v={src ? `${src.sources_ok}/${src.sources_total}` : dash ? 'yok' : '—'} frac={src ? src.sources_ok / Math.max(1, src.sources_total) : null} tone={!src ? 'dim' : src.sources_ok === src.sources_total ? 'ok' : src.sources_ok ? 'warn' : 'bad'} />
        </Box>
        <div className="m2-rings">
          <RingGauge
            label="GÜÇ"
            frac={pilFrac}
            value={pilFrac === null ? '—' : Math.round(pilFrac * 100)}
            unit={pilFrac === null ? undefined : '%'}
            sub={pilFrac === null ? 'pil bilgisi yok' : (cs.charging ?? /şarj/.test(sys.pil ?? '')) ? 'şarj oluyor' : 'pilde'}
            tone={pilFrac !== null && pilFrac < 0.2 && !cs.charging ? 'bad' : 'ok'}
          />
          <RingGauge
            label="İŞLEMCİ"
            frac={sys.cpu}
            value={sys.cpu === null ? '—' : Math.round(sys.cpu * 100)}
            unit={sys.cpu === null ? undefined : '%'}
            sub={sys.ram ? `bellek ${sys.ram}` : 'ölçüm yok'}
            tone={cpuTon}
          />
        </div>
      </aside>

      <main className="m2-center">
        <div className="m2-stagewrap">
          <div className="m2-orbitwrap">
            <Orbit d={dash} hl={[]} dim={dim} />
            <HudCore state={core} level={p.level} introAt={p.introAt} info={{ scene: null }} />
            <div className="m2-statelabel">
              <b>{durumYazi}</b>
              <span>{pomoYazi || 'BLOOM · MARK II'}</span>
            </div>
          </div>
        </div>

        <div className="m2-holo">
          <div className="m2-holo-h">
            <span>{noktalar.length ? 'KONUM' : 'DÜNYA'}</span>
            <span className="m2-meta">{noktalar.length ? noktalar.map(x => x.label).join(' · ') : w ? `${w.city} işaretli` : ''}</span>
          </div>
          <AnimatePresence mode="wait">
            <motion.div key="globe" className="m2-globewrap" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Globe markers={markers} focus={odak} />
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="m2-log">
          <div className="m2-holo-h"><span>GÜNLÜK</span><span className="m2-meta">{st.adimlar.length ? `${st.adimlar.length} adım` : 'boşta'}</span></div>
          {(core === 'thinking' || core === 'speaking' || st.adimlar.length > 0) && st.adimlar.slice(-6).map((l, i) => <div key={i} className="m2-logl">▸ {l}</div>)}
          {core === 'idle' && st.adimlar.length === 0 && <div className="m2-logl dim">komut bekleniyor</div>}
          {core === 'listening' && <div className="m2-logl">▸ mikrofon açık</div>}
        </div>

        <div className="m2-caption">
          <AnimatePresence mode="wait">
            {caption && (
              <motion.p key={caption.slice(0, 40)} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
                <span className="who">{who} ▸</span> {caption}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </main>

      <aside className="m2-right">
        <WeatherDial w={w} highlight={false} />
        <Box title="BUGÜN" meta={pomoYazi ? 'ODAK AÇIK' : takvim.length ? `${takvim.length} kayıt` : ''} className="m2-list">
          {takvim.slice(0, 6).map((a, i) => (
            <div key={i} className={'m2-li' + (a.gecti ? ' past' : '')}>
              <span className="n">{a.a}</span>
              <span className="t">{a.b}{a.gec && <em>gecikti</em>}</span>
            </div>
          ))}
          {!takvim.length && <div className="m2-li dim">{takvimIpucu || 'bugün için kayıt yok'}</div>}
        </Box>
        <Box title="GÜNDEM" meta={src ? `${src.total} haber` : ''} className="m2-list m2-news">
          {(src?.headlines ?? []).slice(0, 6).map((h, i) => (
            <div key={i} className="m2-li">
              <span className="n">{hhmm(h.published_at)}</span>
              <span className="t">{h.title}<em>{h.source}</em></span>
            </div>
          ))}
          {!src?.headlines.length && <div className="m2-li dim">{p.dashDenendi ? 'haber alınamadı' : 'yükleniyor…'}</div>}
        </Box>
      </aside>

      <footer className="m2-dock">
        <form className="m2-cmd" onSubmit={e => { e.preventDefault(); p.onSubmit(p.input); }}>
          <span className="m2-cmd-l">KOMUT</span>
          <input value={p.input} onChange={e => p.setInput(e.target.value)} placeholder="Bloom'a yazın…" enterKeyHint="send" autoComplete="off" spellCheck={false} />
        </form>
        <div className="m2-btns">
          <RoundButton label="Geçmiş" onClick={p.onHistory} active={p.historyOpen}><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10" /></svg></RoundButton>
          <RoundButton label={st.kamAcik ? 'Kamera açık' : 'Kamera'} onClick={p.onCam} active={st.kamAcik}><svg viewBox="0 0 24 24"><rect x="3" y="7" width="13" height="10" rx="2" /><path d="M16 11l5-3v8l-5-3z" /><circle cx="7" cy="10" r="1" /></svg></RoundButton>
          <RoundButton label="Brifing" onClick={() => p.onSubmit('Bloom, günlük brifingimi ver: hava, takvim, görevler ve haberler')}><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></svg></RoundButton>
          <RoundButton label={!st.mikAcik ? 'Mikrofon kapalı' : core === 'listening' ? 'Dinliyor' : 'Mikrofon'} onClick={p.onMic} big active={st.mikAcik && core === 'listening'}><svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />{!st.mikAcik && <path d="M4 4l16 16" />}</svg></RoundButton>
          <RoundButton label="Devam" onClick={() => p.onSubmit('Devam et')}><svg viewBox="0 0 24 24"><path d="M6 5l7 7-7 7M13 5l7 7-7 7" /></svg></RoundButton>
          <RoundButton label="Uyku" onClick={p.onSleep} active={st.durum === 'asleep'}><svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /></svg></RoundButton>
          <RoundButton label="El" onClick={p.onHands}><svg viewBox="0 0 24 24"><path d="M8 12V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4a1.5 1.5 0 0 1 3 0v6.5M14 10.5V5.5a1.5 1.5 0 0 1 3 0V13M8 11.5a1.5 1.5 0 0 0-3 0V14a7 7 0 0 0 7 7h1a6 6 0 0 0 6-6V9.5a1.5 1.5 0 0 0-3 0" /></svg></RoundButton>
          <RoundButton label="Panel" onClick={p.onPanel}><svg viewBox="0 0 24 24"><rect x="4" y="4" width="7" height="7" /><rect x="13" y="4" width="7" height="7" /><rect x="4" y="13" width="7" height="7" /><rect x="13" y="13" width="7" height="7" /></svg></RoundButton>
          <RoundButton label="Modeller" onClick={p.onModel}><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><circle cx="12" cy="12" r="8" /><path d="M12 4V2M12 22v-2M4 12H2M22 12h-2" /></svg></RoundButton>
          <RoundButton label="Ayarlar" onClick={p.onSettings}><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></svg></RoundButton>
        </div>
      </footer>
      {p.overlay}
    </div>
  );
}
