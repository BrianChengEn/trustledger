import {useState} from 'react';
import {labels} from './api';
import {Icon} from './icons';
import {memoryCategory, memoryModeCopy, memoryStore, prettyCategory} from './lib';
import Pager from './Pager';
import {Callout, Chip, PageHead, stagger} from './ui';
import {useWorkspace} from './workspace';

/** Memory is the management view: what was allowed, where it lives, what it affects, and how to remove it. */
export default function MemoryView() {
  const {memories, alerts, transactions, health, forget, busy, loading, refresh, ready, go, href} = useWorkspace();
  const [confirming, setConfirming] = useState<string | null>(null);
  const mode = memoryModeCopy(health?.memory_mode);
  const affected = (summary: string) => {
    const category = memoryCategory(summary);
    if (!category || category === 'other') return [];
    return alerts.filter(a => transactions.find(t => t.id === a.transaction_id)?.merchant_category === category)
      .map(a => ({alert: a, tx: transactions.find(t => t.id === a.transaction_id)!}));
  };
  return <div className="page">
    <PageHead eyebrow="Memory" title="What you’ve allowed it to remember."
      actions={<button className="iconbtn" aria-label="Refresh memories" onClick={() => void refresh()} disabled={loading || busy}><Icon name="refresh" size={16}/></button>}>
      TrustLedger remembers only category-level preferences you explicitly approve. Never a merchant, an amount or an ID.</PageHead>
    <Callout tone={mode.tone === 'good' ? 'good' : mode.tone === 'warn' ? 'warn' : 'neutral'} icon="hardDrive" title={`Storage: ${mode.label}`}>{mode.detail}</Callout>

    {!memories.length ? <div className="empty memempty">
      <Icon name="hardDrive" size={28}/>
      <h2>Nothing is remembered yet.</h2>
      <p>When you mark an alert normal, you can choose to let TrustLedger remember that preference. Until you opt in, nothing is stored.</p>
      <button className="primary" onClick={() => go({view: 'today'})}>Review an alert<Icon name="arrowRight" size={16}/></button>
    </div> : <>
    <ul className="memlist">
      {memories.map((m, i) => {
        const store = memoryStore(m.source);
        const touched = affected(m.summary);
        return <li key={m.memory_id} className="memory panel" style={stagger(i)}>
          <div className="memtop">
            <Chip tone={store.tone === 'good' ? 'good' : 'neutral'} icon={m.source === 'backboard' ? 'database' : 'hardDrive'}>{store.label}</Chip>
            <small>Saved {new Date(m.created_at).toLocaleString()}</small>
          </div>
          <blockquote>{m.summary}</blockquote>
          <p className="quiet">{store.detail}</p>
          <div className="effect"><b>How context is checked</b>
            {memoryCategory(m.summary) === 'other' ? <p>This saved confirmation has no specific category evidence. It is not matched to other transactions or used as a prior confirmation.</p> : <p>For <em>{memoryCategory(m.summary) ? prettyCategory(memoryCategory(m.summary)!) : 'this category'}</em> charges, eligible consented records may provide “prior confirmation: normal” as context. The case view checks eligibility and provider status. Rules still decide and the alert is still shown.</p>}
            {touched.length > 0 && <ul>{touched.map(({alert, tx}) => <li key={alert.alert_id}>
              <a href={href({view: 'case', tx: tx.id})}>{tx.merchant_display}: {labels[alert.alert_type]}</a></li>)}</ul>}
          </div>
          <div className="actions">
            {confirming === m.memory_id ? <>
              <button className="danger" disabled={busy || !ready} onClick={async () => { await forget(m.memory_id); setConfirming(null); }}>
                <Icon name="trash" size={16}/>{busy ? 'Deleting…' : 'Yes, delete this memory'}</button>
              <button disabled={busy} onClick={() => setConfirming(null)}>Keep it</button></>
              : <button disabled={busy || !ready} onClick={() => setConfirming(m.memory_id)}><Icon name="trash" size={16}/>Delete memory</button>}
          </div>
        </li>;
      })}
    </ul>
    <Pager/>
    </>}
  </div>;
}
