import type {ReactNode} from 'react';
import {money, type Alert} from './api';
import {cellsUsed, WIDGET_CELLS, WIDGETS, widgetStore, useWidgets} from './homeStore';
import {Icon, type IconName} from './icons';
import {dataModeCopy, day, memoryModeCopy} from './lib';
import Pager from './Pager';
import {stagger} from './ui';
import {useWorkspace} from './workspace';

const alertIcons: Record<Alert['alert_type'], IconName> = {
  duplicate: 'copy', amount_anomaly: 'alertTriangle', subscription_change: 'trendingUp', none: 'checkCircle',
};
// Short names on purpose: the Review queue above owns the full alert labels.
const shortName: Record<Alert['alert_type'], string> = {
  duplicate: 'Duplicate charge', amount_anomaly: 'Large amount', subscription_change: 'Price increase', none: 'No rule',
};

/** Customizable mini tools under the Review queue. Layout is the user's own and is saved in this browser. */
export default function Widgets() {
  const {ids, editing, gallery} = useWidgets();
  const {transactions, alerts, memories, health, ready, go} = useWorkspace();

  const open = alerts.filter(a => a.status === 'open');
  const byDate = [...transactions].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
  const maxAmount = Math.max(1, ...byDate.map(t => t.amount));
  const spending = transactions.filter(t => t.direction === 'debit').reduce((n, t) => n + t.amount, 0);
  const largest = transactions.filter(t => t.direction === 'debit' && t.kind === 'purchase')
    .sort((a, b) => b.amount - a.amount)[0];
  const subscriptions = [...new Map(byDate.filter(t => t.is_subscription && t.direction === 'debit').map(t => [t.merchant_display, t])).values()];
  const subscriptionTotal = subscriptions.reduce((n, t) => n + t.amount, 0);
  const flagged = (id: string) => alerts.some(a => a.transaction_id === id);
  const priorityTx = (open[0] ?? alerts[0])?.transaction_id ?? transactions[0]?.id;
  const data = dataModeCopy(ready ? health?.data_mode : 'degraded'), memory = memoryModeCopy(health?.memory_mode);

  const target: Record<string, () => void> = {
    spending: () => go({view: 'activity'}),
    status: () => go({view: 'sources'}),
    alerts: () => open[0] ? go({view: 'case', tx: open[0].transaction_id, from: 'today'}) : go({view: 'activity', filter: 'flagged'}),
    privacy: () => go({view: 'privacy', tx: priorityTx}),
    memory: () => go({view: 'memory'}),
    recurring: () => go({view: 'activity', filter: 'recurring'}),
    largest: () => largest ? go({view: 'case', tx: largest.id, from: 'activity'}) : go({view: 'activity'}),
    nessie: () => go({view: 'sources'}),
  };

  const body = (id: string): ReactNode => {
    switch (id) {
      case 'spending': return <>
        <span className="wbig"><span className="num">{money(spending)}</span><span className="unit">across {transactions.length} {transactions.some(t => t.source === 'nessie') ? 'Nessie sandbox' : 'synthetic'} transactions</span></span>
        <span className="spend" aria-hidden="true">{byDate.map(t =>
          <span key={t.id} className={'spendbar' + (flagged(t.id) ? ' flag' : '')} style={{height: `${Math.max(10, t.amount / maxAmount * 100)}%`}}/>)}</span></>;
      case 'status': return <span className="wlist cols">
        {([['Data', data.label], ['Analysis', 'Rules decide'], ['Memory', memory.label]] as [string, string][]).map(([label, value]) =>
          <span className="wcol" key={label}><small>{label}</small><b>{value}</b></span>)}</span>;
      case 'alerts': return <>
        <span className="wbig"><span className="num">{open.length}</span><span className="unit">to review</span></span>
        <span className="wlist">{open.slice(0, 2).map(a => { const t = transactions.find(i => i.id === a.transaction_id);
          return <span className="wrow" key={a.alert_id}><span className="icontile alert small"><Icon name={alertIcons[a.alert_type]} size={14}/></span>
            <span className="wtext"><b>{shortName[a.alert_type]}</b><small>{t?.merchant_display}</small></span><span className="wvalue">{t ? money(t.amount) : ''}</span></span>; })}
          {!open.length && <span className="wnote">All reviewed. Nothing needs you.</span>}</span></>;
      case 'privacy': return <>
        <span className="wbig"><span className="num">8</span><span className="unit">fields can be shared</span></span>
        <span className="wnote">No IDs or merchant names.</span></>;
      case 'memory': return <>
        <span className="wbig"><span className="num">{memories.length}</span><span className="unit">{memories.length === 1 ? 'preference saved' : 'preferences saved'}</span></span>
        <span className="wnote">{memories.length ? `Latest ${day(memories[0].created_at)}` : 'Nothing remembered.'}</span></>;
      case 'recurring': return <>
        <span className="wbig"><span className="num">{subscriptions.length}</span><span className="unit">subscriptions</span></span>
        <span className="wnote">{money(subscriptionTotal)} latest charges</span></>;
      case 'largest': return <>
        <span className="wbig"><span className="num">{largest ? money(largest.amount) : '—'}</span><span className="unit">largest charge</span></span>
        <span className="wnote">{largest ? `${largest.merchant_display} · ${day(largest.occurred_at)}` : ''}</span></>;
      case 'nessie': return <>
        <span className="wbig"><span className="num">8</span><span className="unit">read-only queries</span></span>
        <span className="wnote">Capital One Nessie sandbox</span></>;
      default: return null;
    }
  };

  const remaining = WIDGET_CELLS - cellsUsed(ids);
  const unused = WIDGETS.filter(w => !ids.includes(w.id));

  return <section className="widgets" aria-label="Widgets">
    <div className="widgetshead">
      <h2>Widgets</h2>
      <div className="headactions">
        {editing && <button className="small ghost" onClick={() => widgetStore.reset()}>Reset</button>}
        <button className={'small' + (editing ? ' primary' : '')} aria-pressed={editing} onClick={() => widgetStore.setEditing(!editing)}>
          <Icon name={editing ? 'check' : 'sliders'} size={15}/>{editing ? 'Done' : 'Edit'}</button>
      </div>
    </div>
    <div className={'widgetgrid' + (editing ? ' editing' : '')}>
      {ids.map((id, i) => { const def = WIDGETS.find(w => w.id === id); if (!def) return null;
        return <div key={id} className={'wcell size' + def.size} style={stagger(i)}>
          <button className="widget" tabIndex={editing ? -1 : 0} aria-hidden={editing ? true : undefined} onClick={editing ? undefined : target[id]}>
            <span className="whead"><span className={'icontile small' + (id === 'alerts' ? ' alert' : '')}><Icon name={def.icon} size={15}/></span>
              <span className="wlabel">{def.name}</span>{!editing && <Icon name="arrowRight" size={14}/>}</span>
            <span className="wbody">{body(id)}</span>
          </button>
          {editing && <span className="wtools">
            <button className="wbtn remove" aria-label={`Remove ${def.name}`} onClick={() => widgetStore.remove(id)}><Icon name="minus" size={14}/></button>
            <span className="wmove">
              <button className="wbtn" aria-label={`Move ${def.name} earlier`} disabled={i === 0} onClick={() => widgetStore.move(id, -1)}><Icon name="arrowLeft" size={14}/></button>
              <button className="wbtn" aria-label={`Move ${def.name} later`} disabled={i === ids.length - 1} onClick={() => widgetStore.move(id, 1)}><Icon name="arrowRight" size={14}/></button>
            </span></span>}
        </div>; })}
      {editing && remaining > 0 && unused.length > 0 && <button className="wadd" aria-expanded={gallery} onClick={() => widgetStore.setGallery(!gallery)}>
        <Icon name="plus" size={22}/>Add widget</button>}
    </div>
    {editing && gallery && <div className="gallery" role="region" aria-label="Add a widget">
      <div className="galleryhead"><strong>Add a widget</strong>
        <button className="iconbtn" aria-label="Close widget gallery" onClick={() => widgetStore.setGallery(false)}><Icon name="x" size={16}/></button></div>
      <div className="gallerylist">{unused.map(w => { const fits = w.size <= remaining;
        return <button key={w.id} className="galleryitem" disabled={!fits} onClick={() => widgetStore.add(w.id)}>
          <span className="icontile small"><Icon name={w.icon} size={15}/></span>
          <span className="menutext"><b>{w.name}</b><small>{fits ? w.blurb : 'Not enough room. Remove a widget first.'}</small></span>
          <span className="chip">{w.size === 2 ? 'Wide' : 'Small'}</span></button>; })}</div>
      <Pager/>
    </div>}
  </section>;
}
