import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Icon, type IconName} from './icons';
import {dataModeCopy, memoryModeCopy, type Tone} from './lib';
import {useRoute, go, type Route} from './route';
import {Admin, SourcesIntro} from './Sources';
import {WorkspaceProvider, useWorkspace} from './workspace';
import WorkspaceView from './WorkspaceView';
import './styles.css';

const nav: {view: Route['view']; label: string; icon: IconName; id?: string}[] = [
  {view: 'today', label: 'Today', icon: 'bell'},
  {view: 'activity', label: 'Activity', icon: 'wallet'},
  {view: 'privacy', label: 'Privacy', icon: 'lock'},
  {view: 'memory', label: 'Memory', icon: 'hardDrive'},
  {view: 'sources', label: 'Data sources', icon: 'database', id: 'NAV-ADMIN'},
];

/** Truthful system status. /health describes readiness, never the outcome of an individual analysis. */
function StatusMenu() {
  const {health, runs, transactions, ready, loading} = useWorkspace();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = () => setOpen(false);
    window.addEventListener('hashchange', close);
    return () => window.removeEventListener('hashchange', close);
  }, []);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [open]);
  const data = dataModeCopy(!ready && !loading ? 'degraded' : health?.data_mode), mem = memoryModeCopy(health?.memory_mode);
  const done = Object.entries(runs).flatMap(([id, r]) => r.state === 'done' ? [{id, ...r}] : []).sort((a, b) => b.at - a.at)[0];
  const last = done && {tx: transactions.find(t => t.id === done.id)?.merchant_display ?? done.id, mode: done.result.provider_mode};
  const lastText = !last ? 'No AI analysis requested yet this session.'
    : last.mode === 'rules+jev-live' ? `Last analysis (${last.tx}): live Jev succeeded.`
    : last.mode === 'degraded' ? `Last analysis (${last.tx}): AI failed, rules result used.`
    : `Last analysis (${last.tx}): rules only, no AI provider used.`;
  const rows: {icon: IconName; title: string; value: string; tone: Tone; text: string}[] = [
    {icon: 'database', title: 'Data', value: data.label, tone: data.tone, text: data.detail},
    {icon: 'listChecks', title: 'Analysis', value: 'Rules decide', tone: 'neutral',
      text: `Deterministic rules are authoritative. Live Jev runs only when you request it, and its outcome is shown on that analysis. ${lastText}`},
    {icon: 'hardDrive', title: 'Memory', value: mem.label, tone: mem.tone, text: mem.detail},
  ];
  return <div className="statusmenu" ref={box}>
    <button className="statusbtn" aria-expanded={open} aria-controls="status-panel" onClick={() => setOpen(o => !o)}>
      <span className={'dot tone-' + (health ? (health.status === 'ok' ? 'good' : 'warn') : 'neutral')} aria-hidden="true"/>
      <span className="statuslabel">{health ? `${data.label} · ${mem.label}` : 'Connecting…'}</span><Icon name="chevronDown" size={14}/>
    </button>
    {open && <div id="status-panel" className="statuspanel" role="region" aria-label="System status">
      {rows.map(r => <div key={r.title} className="statusrow"><span className={'icontile small tone-' + r.tone}><Icon name={r.icon} size={14}/></span>
        <div><b>{r.title}</b> <span className={'chip tone-' + r.tone}>{r.value}</span><p>{r.text}</p></div></div>)}
      <p className="statusnote">Status reflects server readiness, not any one analysis. A configured key never means a live AI request succeeded.</p>
    </div>}
  </div>;
}

function Shell() {
  const route = useRoute();
  const {alerts, memories} = useWorkspace();
  const open = alerts.filter(a => a.status === 'open').length;
  const sources = route.view === 'sources' || !!route.customer;
  const active = sources ? 'sources' : route.view === 'case' ? 'today' : route.view;
  const badge = (view: Route['view']) => view === 'today' ? open : view === 'memory' ? memories.length : 0;
  return <div className="app">
    <header className="topbar">
      <a className="logo" href="#/today" aria-label="TrustLedger home"><span className="logomark"><Icon name="shieldCheck" size={20} weight={1.5}/></span>
        <span>TrustLedger<small>Synthetic demo</small></span></a>
      <nav aria-label="Main">
        {nav.map(n => <a key={n.view} id={n.id} href={'#/' + n.view} className={'navlink' + (active === n.view ? ' active' : '')}
          aria-current={active === n.view ? 'page' : undefined} onClick={e => { if (active === n.view && n.view !== 'privacy') { e.preventDefault(); go({view: n.view} as Route); } }}>
          <Icon name={n.icon} size={17}/><span>{n.label}</span>{badge(n.view) > 0 && <b className="count" aria-label={`${badge(n.view)} items`}>{badge(n.view)}</b>}</a>)}
      </nav>
      <StatusMenu/>
    </header>
    <main id="main">
      <WorkspaceView route={sources ? {view: 'sources'} : route}/>
      <div hidden={!sources} className="adminview"><SourcesIntro/><Admin active={sources}/></div>
    </main>
    <footer className="foot">Synthetic data only · no real accounts · rules decide, you confirm · AI-assisted code, credited in the submission.</footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><WorkspaceProvider><Shell/></WorkspaceProvider></React.StrictMode>);
