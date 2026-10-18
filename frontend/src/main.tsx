import React, {Suspense, lazy, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {type Alert} from './api';
import {widgetStore} from './homeStore';
import {Icon, type IconName} from './icons';
import {dataModeCopy, memoryModeCopy, type Tone} from './lib';
import {useRoute, go, type Route} from './route';
import AdminDemo from './AdminDemo';
// Loaded on demand: the lab ships about 150 KB of research data that the rest of the app never needs.
const FraudLab = lazy(() => import('./fraudlab/FraudLab'));
import {AuthProvider, useAuth} from './auth';
import Login from './Login';
import {Admin, SourcesIntro} from './Sources';
import ThemeSwitch from './ThemeSwitch';
import {stagger} from './ui';
import {WorkspaceProvider, useWorkspace} from './workspace';
import WorkspaceView from './WorkspaceView';
import './scrollLock';
import './styles.css';

// Keep one scale for each viewport; content changes stay inside their own panels.
const STAGE_W = 1360, STAGE_H = 920, STAGE_MAX_SCALE = 1.25;
function applyStage() {
  const root = document.documentElement;
  const w = window.innerWidth, h = window.innerHeight;
  if (window.matchMedia('(max-width: 699px) and (pointer: coarse)').matches) {
    root.removeAttribute('data-stage');
    for (const name of ['--stage-scale', '--stage-w', '--stage-h']) root.style.removeProperty(name);
    return;
  }
  const scale = Math.min(h / STAGE_H, w / STAGE_W, STAGE_MAX_SCALE);
  root.dataset.stage = 'on';
  root.style.setProperty('--stage-scale', String(scale));
  root.style.setProperty('--stage-w', `${w / scale}px`);
  root.style.setProperty('--stage-h', `${h / scale}px`);
}
applyStage();
window.addEventListener('resize', applyStage);

type NavItem = {view: Route['view']; label: string; icon: IconName; id?: string};
const userNav: NavItem[] = [
  {view: 'today', label: 'Today', icon: 'bell'},
  {view: 'activity', label: 'Activity', icon: 'wallet'},
  {view: 'privacy', label: 'Privacy', icon: 'lock'},
  {view: 'memory', label: 'Memory', icon: 'hardDrive'},
];
const adminNav: NavItem[] = [
  {view: 'admin', label: 'Demo data', icon: 'pencil'},
  {view: 'sources', label: 'Data sources', icon: 'database', id: 'NAV-ADMIN'},
];

interface MenuItem {label: string; hint: string; icon: IconName; go: () => void; disabled?: boolean}
interface Menu {eyebrow: string; title: string; blurb: string; groups: {heading: string; items: MenuItem[]}[]}

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
      <span className="statuslabel">{health ? data.label : 'Connecting…'}</span><Icon name="chevronDown" size={14}/>
    </button>
    {open && <div id="status-panel" className="statuspanel" role="region" aria-label="System status">
      {rows.map(r => <div key={r.title} className="statusrow"><span className={'icontile small tone-' + r.tone}><Icon name={r.icon} size={14}/></span>
        <div><b>{r.title}</b> <span className={'chip tone-' + r.tone}>{r.value}</span><p>{r.text}</p></div></div>)}
      <p className="statusnote">Status reflects server readiness, not any one analysis. A configured key never means a live AI request succeeded.</p>
    </div>}
  </div>;
}

function Shell({mode}: {mode: 'user' | 'admin'}) {
  const route = useRoute();
  const auth = useAuth();
  const nav = mode === 'admin' ? adminNav : userNav;
  const {alerts, transactions, memories, health} = useWorkspace();
  // Shortcut menus open only when asked (the caret next to a tab) and close on outside click, Escape or navigation.
  const [menu, setMenu] = useState<Route['view'] | null>(null);
  useEffect(() => {
    const close = () => setMenu(null);
    window.addEventListener('hashchange', close);
    return () => window.removeEventListener('hashchange', close);
  }, []);
  useEffect(() => {
    if (!menu) return;
    const away = (e: MouseEvent) => { if (!(e.target as Element | null)?.closest('.navgroup')) setMenu(null); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(null); };
    document.addEventListener('mousedown', away); document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc); };
  }, [menu]);

  const open = alerts.filter(a => a.status === 'open').length;
  const sources = mode === 'admin' && (route.view === 'sources' || !!route.customer);
  const adminPage = mode === 'admin' && route.view === 'admin';
  // Each role only sees its own pages; anything else goes home.
  const allowed = mode === 'admin' ? adminPage || sources || route.view === 'fraudlab' : route.view !== 'admin' && route.view !== 'sources' && !route.customer;
  useEffect(() => {
    if (!allowed) go(mode === 'admin' ? {view: 'admin'} : {view: 'today'});
  }, [allowed, mode]);
  const active = sources ? 'sources' : adminPage ? 'admin' : route.view === 'case' ? 'today' : route.view;
  const badge = (view: Route['view']) => mode === 'user' ? (view === 'today' ? open : view === 'memory' ? memories.length : 0) : 0;

  // Sub-features shown in the drop-down menus (each jumps straight to the right place).
  const firstOf = (type: Alert['alert_type']) => alerts.find(a => a.alert_type === type)?.transaction_id;
  const caseOf = (id?: string) => () => { if (id) go({view: 'case', tx: id, from: 'today'}); };
  const firstOpen = alerts.find(a => a.status === 'open')?.transaction_id;
  const priorityTx = firstOpen ?? alerts[0]?.transaction_id ?? transactions[0]?.id;
  const flagged = transactions.filter(t => alerts.some(a => a.transaction_id === t.id)).length;
  const recurring = transactions.filter(t => t.is_subscription).length;
  const consoleGo = (button: string) => () => { go({view: 'sources'}); document.getElementById(button)?.click(); };
  const menus: Partial<Record<Route['view'], Menu>> = mode === 'admin' ? {
    admin: {eyebrow: 'DEMO DATA', title: 'Edit the demo.', blurb: 'Change synthetic charges, then preview what the user sees.', groups: [
      {heading: 'Demo data', items: [
        {label: 'Charges', hint: 'Add, edit or delete synthetic charges', icon: 'wallet', go: () => go({view: 'admin'})},
        {label: 'Change log', hint: 'Every edit, scenario and reset', icon: 'clock', go: () => go({view: 'admin', tab: 'log'})},
      ]},
    ]},
    sources: {eyebrow: 'DATA SOURCES', title: 'Where transactions come from.', blurb: 'The workspace works the same whichever source feeds it.', groups: [
      {heading: 'Capital One Nessie sandbox', items: [
        {label: 'Run a query', hint: 'Eight read-only functions', icon: 'search', go: consoleGo('NAV-Q')},
        {label: 'Query history', hint: 'Status and timing only', icon: 'clock', go: consoleGo('NAV-H')},
      ]},
    ]},
  } : {
    today: {eyebrow: 'TODAY', title: 'What needs you first.', blurb: 'Review the charges the rules flagged, then check the rest of your day.', groups: [
      {heading: 'Review', items: [
        {label: 'Duplicate charges', hint: 'Same merchant and amount within 24 hours', icon: 'copy', go: caseOf(firstOf('duplicate')), disabled: !firstOf('duplicate')},
        {label: 'Large amounts', hint: 'Above the demo high-amount threshold', icon: 'alertTriangle', go: caseOf(firstOf('amount_anomaly')), disabled: !firstOf('amount_anomaly')},
        {label: 'Subscription increases', hint: 'A recurring charge rose by more than 20%', icon: 'trendingUp', go: caseOf(firstOf('subscription_change')), disabled: !firstOf('subscription_change')},
      ]},
      {heading: 'Learn', items: [
        {label: 'Fraud Intelligence Lab', hint: 'Offline ML research on BankSim: model, evidence, benchmarks', icon: 'sparkles', go: () => go({view: 'fraudlab'})},
      ]},
      {heading: 'Make it yours', items: [
        {label: 'Edit widgets', hint: 'Remove or reorder your mini tools', icon: 'sliders', go: () => { go({view: 'today'}); widgetStore.setEditing(true); }},
        {label: 'Add a widget', hint: 'Spending, privacy, memory and more', icon: 'plus', go: () => { go({view: 'today'}); widgetStore.setEditing(true); widgetStore.setGallery(true); }},
      ]},
    ]},
    activity: {eyebrow: 'ACTIVITY', title: 'Every transaction.', blurb: 'Find any charge, whatever its alert status.', groups: [
      {heading: 'Browse', items: [
        {label: 'All transactions', hint: `${transactions.length} ${transactions.some(t => t.source === 'nessie') ? 'Nessie sandbox' : 'synthetic'} records`, icon: 'wallet', go: () => go({view: 'activity'})},
        {label: 'Flagged only', hint: `${flagged} with an alert`, icon: 'bell', go: () => go({view: 'activity', filter: 'flagged'})},
        {label: 'Recurring charges', hint: `${recurring} subscriptions`, icon: 'repeat', go: () => go({view: 'activity', filter: 'recurring'})},
      ]},
    ]},
    privacy: {eyebrow: 'PRIVACY', title: 'What AI actually sees.', blurb: 'Your transactions are never sent as they are.', groups: [
      {heading: 'Inspect', items: [
        {label: 'Privacy Inspector', hint: 'What AI may receive, and what is removed', icon: 'lock', go: () => go({view: 'privacy', tx: priorityTx}), disabled: !priorityTx},
        {label: 'Safe payload', hint: 'The eight generalized fields, exactly', icon: 'layers', go: () => go({view: 'privacy', tx: priorityTx}), disabled: !priorityTx},
        {label: 'Your decision', hint: 'Mark a charge normal or review, with consent', icon: 'checkCircle', go: caseOf(firstOpen), disabled: !firstOpen},
      ]},
      {heading: 'Learn', items: [
        {label: 'Privacy Lab', hint: 'Step through what each AI service receives', icon: 'sparkles', go: () => go({view: 'privacy', lab: ''})},
      ]},
    ]},
    memory: {eyebrow: 'MEMORY', title: 'What you’ve allowed it to remember.', blurb: 'Only category-level preferences you approve. Delete them anytime.', groups: [
      {heading: 'Saved preferences', items: [
        {label: 'Saved preferences', hint: `${memories.length} stored`, icon: 'hardDrive', go: () => go({view: 'memory'})},
        {label: 'Remove a memory', hint: 'Delete any stored preference', icon: 'trash', go: () => go({view: 'memory'})},
      ]},
      {heading: 'Learn', items: [
        {label: 'Memory Lab', hint: 'How a charge becomes a memory and helps later', icon: 'sparkles', go: () => go({view: 'memory', lab: ''})},
      ]},
    ]},
  };

  return <div className="app">
    <div className="frame">
    <header className="topbar">
      <a className="logo" href="#/today" aria-label="TrustLedger home"><span className="logomark"><Icon name="shieldCheck" size={20} weight={1.4}/></span>
        <span>TrustLedger<small>{health?.data_mode === 'nessie-live' ? 'Nessie sandbox' : health?.data_mode === 'synthetic' ? 'Synthetic test' : 'Data unavailable'}</small></span></a>
      <nav aria-label="Main">
        {nav.map((n, index) => {
          const m = menus[n.view]; const isOpen = menu === n.view;
          return <div key={n.view} className={'navgroup' + (index >= nav.length - 2 && mode === 'user' ? ' right' : '')}>
            <a id={n.id} href={'#/' + n.view} className={'navlink' + (active === n.view ? ' active' : '')}
              aria-current={active === n.view ? 'page' : undefined}
              onClick={e => {
                setMenu(null);
                if (active === n.view && n.view !== 'privacy') { e.preventDefault(); go({view: n.view} as Route); }
              }}>
              <Icon name={n.icon} size={17}/><span>{n.label}</span>{badge(n.view) > 0 && <b className="count" aria-label={`${badge(n.view)} items`}>{badge(n.view)}</b>}</a>
            {m && <button className="navcaret" aria-label={`Show ${n.label} shortcuts`} aria-haspopup="true" aria-expanded={isOpen}
              aria-controls={`menu-${n.view}`} onClick={() => setMenu(cur => cur === n.view ? null : n.view)}><Icon name="chevronDown" size={14}/></button>}
            {m && isOpen && <div id={`menu-${n.view}`} className="megamenu" role="region" aria-label={`${n.label} features`}>
              <div className="mega-inner">
                <div className="mega-intro"><strong>{m.title}</strong><p>{m.blurb}</p></div>
                <div className="mega-groups">{m.groups.map(g => <div key={g.heading} className="mega-group">
                  <span className="mega-heading">{g.heading}</span>
                  {g.items.map((it, i) => <button key={it.label} className="menuitem" style={stagger(i)} disabled={it.disabled}
                    onClick={() => { setMenu(null); it.go(); }}>
                    <span className="icontile small"><Icon name={it.icon} size={15}/></span>
                    <span className="menutext"><b>{it.label}</b><small>{it.hint}</small></span></button>)}
                </div>)}</div>
              </div>
            </div>}
          </div>;
        })}
      </nav>
      <ThemeSwitch/>
      <StatusMenu/>
      <div className="accountbar">
        {!auth.previewing && <span className={'rolechip' + (mode === 'admin' ? ' admin' : '')}><Icon name={mode === 'admin' ? 'key' : 'shieldCheck'} size={13}/>{mode === 'admin' ? 'Admin' : 'User'}</span>}
        {auth.session.role === 'admin' && (mode === 'admin'
          ? <button key="preview" className="small" onClick={() => { auth.startPreview(); go({view: 'today'}); }}>Preview as user</button>
          : <button key="back" className="small primary" onClick={() => { auth.stopPreview(); go({view: 'admin'}); }}>Back to admin</button>)}
        <button className="small" aria-label="Sign out" onClick={() => void auth.logout()}><Icon name="logOut" size={14}/>{!auth.previewing && 'Sign out'}</button>
      </div>
    </header>
    <main id="main">
      {mode === 'user' && allowed && route.view !== 'fraudlab' && <WorkspaceView route={route}/>}
      {allowed && route.view === 'fraudlab' && <Suspense fallback={<p className="loading" role="status">Loading the research lab…</p>}><FraudLab chapter={route.chapter}/></Suspense>}
      {adminPage && <AdminDemo/>}
      {auth.session.role === 'admin' && <div hidden={!sources} className="adminview"><SourcesIntro/><Admin active={sources}/></div>}
    </main>
    <footer className="foot">Synthetic data only · no real accounts · rules decide, you confirm · AI-assisted code, credited in the submission.</footer>
    </div>
  </div>;
}

/** Sign in first. Users and admins see different screens; the server enforces the same split. */
function Gate() {
  const auth = useAuth();
  if (auth.loading) return <div className="app"><div className="frame loginframe"><p className="quiet splash" role="status">Loading TrustLedger…</p></div></div>;
  if (auth.session.login_required && !auth.session.authenticated) return <Login/>;
  const admin = auth.session.role === 'admin' && !auth.previewing;
  return <WorkspaceProvider><Shell mode={admin ? 'admin' : 'user'}/></WorkspaceProvider>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><AuthProvider><Gate/></AuthProvider></React.StrictMode>);
