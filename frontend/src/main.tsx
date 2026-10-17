import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {request, labels, money, type Transaction, type Alert, type Health, type PrivacyPreview, type Memory, type Confirmation} from './api';
import Admin from './Admin';
import './styles.css';

function App() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [health, setHealth] = useState<Health|null>(null);
  const [selected, setSelected] = useState<string>('');
  const [privacy, setPrivacy] = useState<PrivacyPreview|null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState<'transactions'|'memory'|'admin'>('transactions');
  async function refresh() {
    setLoading(true); setError('');
    try {
      const [h,t,a,m] = await Promise.all([
        request<Health>('/health'), request<Transaction[]>('/transactions'),
        request<Alert[]>('/alerts'), request<Memory[]>('/memories'),
      ]);
      setHealth(h); setTransactions(t); setAlerts(a); setMemories(m);
    } catch {setError('Cannot reach the local API. Start the backend on port 8000, then retry.');}
    finally {setLoading(false);}
  }
  useEffect(() => {void refresh();}, []);
  useEffect(() => {
    let active = true;
    setPrivacy(null); setConsent(false); setNotice('');
    if (selected) request<PrivacyPreview>('/privacy/preview/'+encodeURIComponent(selected))
      .then(p => {if(active)setPrivacy(p);})
      .catch(() => {if(active)setError('Privacy preview could not load. Retry before confirming.');});
    return () => {active = false;};
  }, [selected]);
  const tx = transactions.find(t => t.id === selected);
  const alert = alerts.find(a => a.transaction_id === selected);
  async function confirm(decision: 'normal'|'review') {
    if (!alert || busy || !privacy) return;
    setBusy(true); setError('');
    try {
      const result = await request<Confirmation>('/alerts/'+encodeURIComponent(alert.alert_id)+'/confirmations', {
        method: 'POST', body: JSON.stringify({decision, consent_to_memory: consent}),
      });
      await refresh();
      const next = await request<PrivacyPreview>('/privacy/preview/'+encodeURIComponent(selected));
      setPrivacy(next);
      setNotice(`Confirmed ${result.decision}. Memory: ${result.memory_status} (${health?.memory_mode}).`);
    } catch(e) {setError(e instanceof Error ? e.message : 'Confirmation failed.');}
    finally {setBusy(false);}
  }
  async function removeMemory(id: string) {
    setBusy(true); setError('');
    try {
      await request<void>('/memories/'+encodeURIComponent(id), {method: 'DELETE'});
      await refresh();
      if (selected) setPrivacy(await request<PrivacyPreview>('/privacy/preview/'+encodeURIComponent(selected)));
    }
    catch {setError('Could not delete memory. Please retry.');}
    finally {setBusy(false);}
  }
  return <div className="app">
    <aside className="sidebar"><a className="logo" href="#">T<span>TrustLedger<small>YOUR FINANCIAL GUARDIAN</small></span></a>
      <div className="navlabel">WORKSPACE</div>
      <button className={tab==='transactions'?'active':''} onClick={()=>setTab('transactions')}>Overview & transactions</button>
      <button className={tab==='memory'?'active':''} onClick={()=>setTab('memory')}>Confirmed memory <span>{memories.length}</span></button>
      <button id="NAV-ADMIN" className={tab==='admin'?'active':''} onClick={()=>setTab('admin')}>Admin</button>
      <div className="demobox"><b>Synthetic demo</b><p>One local demo user. No real accounts or money movement.</p><small>Admin offers Nessie sandbox reads. Jev runs through Backboard when configured; memory uses local fallback.</small></div>
    </aside>
    <main><header><span>Personal safety workspace</span><span className="user">Demo user · 001</span></header>
      <div hidden={tab!=='admin'}><Admin/></div>
      <div hidden={tab==='admin'}>
      <section className="heading"><div><div className="eyebrow">YOUR MONEY, WITH CONTEXT</div><h1>{tab==='memory'?'Memory you control.':'A clearer view of your money.'}</h1><p>{tab==='memory'?'Only explicitly approved, sanitized facts are stored.':'Review unusual patterns, see what AI would receive, and decide what happens next.'}</p></div><button onClick={()=>void refresh()} disabled={loading}>Refresh</button></section>
      <div className="modes"><span>Data: {health?.data_mode||'connecting'}</span><span>Analysis: {health?.analysis_mode||'connecting'}</span><span>Memory: {health?.memory_mode||'connecting'}</span></div>
      {error&&<div className="error" role="alert">{error} <button onClick={()=>void refresh()}>Retry</button></div>}
      {notice&&<div className="notice" role="status">{notice}</div>}
      {loading&&!transactions.length?<p role="status">Loading your synthetic workspace…</p>:tab==='memory'?<section className="panel"><h2>Confirmed memory</h2><p>Local SQLite fallback is shown honestly; this is not Backboard live memory.</p>{!memories.length?<div className="empty">No stored facts. Confirm a normal transaction and opt in to create one.</div>:memories.map(m=><article className="memory" key={m.memory_id}><div><span className="badge">{m.source}</span><p>{m.summary}</p><small>{new Date(m.created_at).toLocaleString()}</small></div><button disabled={busy} onClick={()=>void removeMemory(m.memory_id)}>Delete memory</button></article>)}</section>:<>
      <div className="stats"><div><small>Sample spending</small><strong>{money(transactions.filter(t=>t.direction==='debit').reduce((n,t)=>n+t.amount,0))}</strong><span>Across this synthetic fixture, not a monthly total</span></div><div><small>Needs your review</small><strong>{alerts.filter(a=>a.status==='open').length}</strong><span>Rule matches, not fraud probabilities</span></div><div><small>Privacy by default</small><strong>8 safe fields</strong><span>Exact amount, date and merchant are removed</span></div></div>
      <section className="panel alerts"><div className="sectiontop"><h2>Worth a closer look</h2><span>{alerts.length} detected patterns</span></div><div className="alertgrid">{alerts.map(a=>{const t=transactions.find(item=>item.id===a.transaction_id);return <button key={a.alert_id} className={'alertcard '+(a.transaction_id===selected?'selected':'')} onClick={()=>setSelected(a.transaction_id)}><span className={'severity '+a.severity}>{a.severity} · {a.status}</span><b>{labels[a.alert_type]}</b><span>{t?.merchant_display} · {t?money(t.amount):''}</span><small>View evidence & privacy →</small></button>})}</div></section>
      {tx&&<section className="panel detail" aria-label="Selected transaction detail"><div className="sectiontop"><h2>{tx.merchant_display}</h2><button onClick={()=>setSelected('')}>Close</button></div><p>{money(tx.amount)} · {tx.source} · {new Date(tx.occurred_at).toLocaleString()}</p><div className="detailgrid"><div><h3>Why it was flagged</h3>{alert?.evidence.map(e=><p key={e}>{e}</p>)}{!alert&&<p>No demo rule was triggered. You can still inspect the safe payload.</p>}<p className="quiet">{alert?.provider_mode==='rules+jev-live'?`Jev through Backboard (${alert.model_version??'resolved model'}). Confidence 1.0 is the deterministic rule, not a model probability.` : alert?.provider_mode==='degraded'?'Rules fallback. Backboard did not return usable Jev output, so this result is not live.':'Rules-only analysis. Confidence 1.0 means a deterministic rule matched, not certainty of fraud. No external AI call has been made.'}</p>{alert&&<><h3>Your decision</h3><label className="check"><input type="checkbox" checked={consent} disabled={busy||alert.status!=='open'} onChange={e=>setConsent(e.target.checked)}/><span>Remember a sanitized fact if I confirm this is normal. Stored in the local fallback; I can delete it.</span></label><div className="actions"><button className="primary" disabled={busy||!privacy||alert.status!=='open'} onClick={()=>void confirm('normal')}>This is normal</button><button disabled={busy||!privacy||alert.status!=='open'} onClick={()=>void confirm('review')}>Needs review</button></div>{alert.status!=='open'&&<p className="badge">Already confirmed: {alert.status}</p>}</>}</div><div><h3>Privacy Inspector</h3><p>Only these eight safe fields may be sent to Jev through Backboard when configured. Nessie Admin results stay separate.</p>{privacy?<><div className="privacyactions">{privacy.inspection.map(i=><div key={i.field}><b>{i.field}</b><span>{i.action}{i.output?' → '+i.output:''}</span></div>)}</div><pre>{JSON.stringify(privacy.safe_payload,null,2)}</pre></>:<p role="status">Loading privacy preview…</p>}</div></div></section>}
      <section className="panel"><div className="sectiontop"><h2>Transactions</h2><span>{transactions.length} synthetic records</span></div><div className="tablewrap"><table><thead><tr><th>Merchant</th><th>Category</th><th>Date</th><th>Amount</th><th>Inspect</th></tr></thead><tbody>{transactions.map(t=><tr key={t.id}><td><b>{t.merchant_display}</b><small>{t.source}</small></td><td>{t.merchant_category.replaceAll('_',' ')}</td><td>{new Date(t.occurred_at).toLocaleDateString()}</td><td>{money(t.amount)}</td><td><button onClick={()=>setSelected(t.id)}>View</button></td></tr>)}</tbody></table></div></section></>}
      <footer>TrustLedger · Technica 2026 · Synthetic development baseline · No bank connection</footer>
      </div>
    </main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
