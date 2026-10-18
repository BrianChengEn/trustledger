import {useEffect, useState} from 'react';
import {labels, money, request, type Explanation, type Alert, type Transaction} from './api';
import {Icon} from './icons';
import {alertHints, explanationModeCopy, fullDate, isPriorEvidence, memoryCategory, memorySentence, memoryStore, outcomeCopy, prettyCategory} from './lib';
import {usePreview} from './preview';
import RelevantMemory from './RelevantMemory';
import {alertIcons, statusText} from './Today';
import {categoryIcon} from './Activity';
import {Callout, Chip} from './ui';
import {useWorkspace, type Run} from './workspace';

function Step({n, title, tag, children}: {n: number; title: string; tag?: React.ReactNode; children: React.ReactNode}) {
  return <section className="step" aria-labelledby={'step-' + n}>
    <div className="stepnum" aria-hidden="true">{n}</div>
    <div className="stepbody"><div className="steptop"><h2 id={'step-' + n}>{title}</h2>{tag}</div>{children}</div>
  </section>;
}

function Evidence({alert}: {alert: Alert}) {
  return <>
    <p className="rulehead"><b>{labels[alert.alert_type]}</b> · {alertHints[alert.alert_type]}</p>
    <ul className="evidence">{alert.evidence.map(e =>
      <li key={e} className={isPriorEvidence(e) ? 'prior' : ''}>
        <Icon name={isPriorEvidence(e) ? 'hardDrive' : 'search'} size={16}/><span>{e}</span></li>)}</ul>
    <div className="chips">
      <Chip icon="listChecks">Deterministic rule match</Chip>
      <Chip tone={alert.needs_human ? 'warn' : 'neutral'} icon="user">{alert.needs_human ? 'Human review required' : 'No human review required'}</Chip>
    </div>
    <p className="quiet">A rule match is not a fraud probability. It means the pattern was found; whether it is a problem is your call.</p>
  </>;
}

function ExplanationPanel({tx}: {tx: Transaction}) {
  const {prefix, ready} = useWorkspace();
  const [run, setRun] = useState<{state: 'idle'} | {state: 'loading'} | {state: 'done'; result: Explanation} | {state: 'failed'}>({state: 'idle'});
  useEffect(() => { setRun({state: 'idle'}); }, [tx.id]);
  async function load() {
    if (!ready) return;
    setRun({state: 'loading'});
    try {
      const result = await request<Explanation>(
        prefix + '/transactions/' + encodeURIComponent(tx.id) + '/explanation', {method: 'POST'}, 20000);
      setRun({state: 'done', result});
    } catch { setRun({state: 'failed'}); }
  }
  const done = run.state === 'done' ? run.result : null;
  const copy = done ? explanationModeCopy(done.explanation_mode, done.from_cache) : null;
  return <div className="explain">
    <p>Ask for a plain-language explanation of this rules result. Nothing is sent until you press the button, and the alert itself does not change.</p>
    {run.state === 'loading' && <div className="airun" role="status"><span className="spinner" aria-hidden="true"/>
      <div><b>Preparing an explanation</b><p>This can take a few seconds. The rules result above stays as it is.</p></div></div>}
    {run.state === 'failed' && <Callout tone="warn" icon="alertTriangle" title="Explanation request failed" role="alert">
      The alert, evidence, and your decision are unchanged. You can try again.</Callout>}
    {done && copy && <div className="result">
      <Callout tone={copy.tone} icon={done.explanation_mode === 'gemini-live' ? 'sparkles' : 'shieldCheck'} title={copy.title} role="status">{copy.detail}</Callout>
      <dl>
        <dt>Why it was flagged</dt><dd>{done.why_flagged}</dd>
        <dt>Evidence used</dt><dd>{done.supporting_evidence}</dd>
        <dt>What the warning means</dt><dd>{done.what_it_means}</dd>
        <dt>What to check</dt><dd>{done.what_to_check}</dd>
        <dt>What you can do</dt><dd><ul className="evidence">{done.next_steps.map(step => <li key={step}><span>{step}</span></li>)}</ul></dd>
      </dl>
      <details>
        <summary>What an explanation is allowed to use</summary>
        <p className="quiet">{done.sent_to_provider
          ? 'This request sent only the summary below to Gemini.'
          : 'Gemini was not called for this response. This is the only summary an explanation is allowed to use.'}</p>
        <pre className="json" aria-label="Explanation summary sent or prepared">{JSON.stringify(done.shared, null, 2)}</pre>
      </details>
    </div>}
    <div className="actions">
      <button className="ai" disabled={!ready || run.state === 'loading'} onClick={() => void load()}>
        <Icon name="sparkles" size={16}/>{run.state === 'loading' ? 'Preparing…' : done ? 'Explain again' : 'Explain this alert'}</button>
    </div>
  </div>;
}

function AiStep({tx, run, stale, fieldCount, onRun, enabled}: {
  tx: Transaction; run?: Run; stale: boolean; fieldCount: number | null; onRun: () => void; enabled: boolean}) {
  const {href} = useWorkspace();
  const running = run?.state === 'running';
  return <>
    <p>Rules stay in charge. Jev adds a second opinion on a <b>generalized</b> version of this charge{fieldCount ? ` (${fieldCount} fields, no merchant name, no exact amount, no IDs)` : ''}.
      It runs only when you ask, once per click. <a href={href({view: 'privacy', tx: tx.id})}>Inspect exactly what is shared</a></p>
    {run?.state === 'running' && <div className="airun" role="status"><span className="spinner" aria-hidden="true"/>
      <div><b>Analyzing {tx.merchant_display} · {money(tx.amount)}</b><p>Sending the generalized fields to Jev through Backboard. This can take a few seconds…</p></div></div>}
    {run?.state === 'failed' && <Callout tone="warn" icon="alertTriangle" title="Analysis request failed" role="alert">{run.message}</Callout>}
    {run?.state === 'done' && <AiResult result={run.result}/>}
    {run?.state === 'done' && stale && <Callout tone="neutral" icon="info" title="Your memories changed since this analysis">
      Run it again to include your latest saved preferences as context.</Callout>}
    <div className="actions">
      <button className="ai" disabled={running || !enabled} onClick={onRun}>
        <Icon name="sparkles" size={16}/>{running ? 'Analyzing…' : run ? 'Run analysis again' : 'Analyze with Jev'}</button>
      {!run && <span className="quiet">Nothing is sent until you press this.</span>}
    </div>
  </>;
}

function AiResult({result}: {result: NonNullable<Extract<Run, {state: 'done'}>['result']>}) {
  const prior = result.evidence.some(isPriorEvidence);
  const id = result.request_id.slice(0, 8);
  const rule = <p className="ruleline"><Icon name="listChecks" size={15}/><span>Rules outcome (authoritative): <b>{labels[result.alert_type]}</b>
    {result.needs_human ? ', human review required' : ''}. Unchanged by this analysis.</span></p>;
  const context = <p className="ruleline"><Icon name="hardDrive" size={15}/><span>{prior
    ? 'Context used: you previously confirmed this category as normal. It informs the analysis but did not hide the alert.'
    : 'Context used: no saved preference for this category.'}</span></p>;
  if (result.provider_mode === 'rules+jev-live') return <div className="result tone-ai">
    <Callout tone="ai" icon="sparkles" title="Live Jev analysis completed" role="status">
      Request succeeded through Backboard{result.model_version ? ` using ${result.model_version}` : ''}. Reference {id}.</Callout>
    {rule}{context}
    <p className="quiet">This confirms Jev was reached and returned a usable assessment. It does not mean Jev independently confirmed fraud, and the API does not return Jev’s individual findings yet, so none are shown here.</p>
  </div>;
  if (result.provider_mode === 'degraded') return <div className="result tone-warn">
    <Callout tone="warn" icon="alertTriangle" title="AI unavailable, rules result shown" role="status">
      Jev did not return a usable result for this request, so this is not a live AI analysis. Nothing is lost: the rules outcome below stands. Reference {id}.</Callout>
    {rule}{context}
  </div>;
  return <div className="result">
    <Callout icon="shieldCheck" title="Rules-only analysis" role="status">
      AI analysis is not enabled on this server, so nothing was sent to any AI provider. Reference {id}.</Callout>
    {rule}{context}
  </div>;
}

function Decision({alert, tx, enabled}: {alert: Alert; tx: Transaction; enabled: boolean}) {
  const {confirm, busy, health, outcomes, memories, revision, go} = useWorkspace();
  const [choice, setChoice] = useState<'normal' | 'review' | null>(null);
  const [consent, setConsent] = useState(false);
  const memoryOff = health?.memory_mode === 'off';
  const outcome = outcomes[tx.id];
  const saved = outcome?.memory_id ? memories.find(m => m.memory_id === outcome.memory_id) : undefined;
  useEffect(() => { setChoice(null); setConsent(false); }, [alert.alert_id, revision]);

  if (alert.status !== 'open') {
    const o = outcome && outcomeCopy(outcome, saved?.source);
    return <>
      <Callout tone={alert.status === 'normal' ? 'good' : 'warn'} icon={alert.status === 'normal' ? 'checkCircle' : 'search'}
        title={alert.status === 'normal' ? 'You marked this normal' : 'You marked this for review'} role="status">
        {alert.status === 'normal'
          ? 'The alert stays in your history and the rules will keep checking similar charges.'
          : 'It stays flagged for your follow-up. TrustLedger took no action on your money.'}</Callout>
      {o ? <Callout tone={o.tone} icon="hardDrive" title={o.title}>{o.detail}</Callout> : <p className="quiet">See Memory for anything saved from this decision.</p>}
      <div className="actions"><button onClick={() => go({view: 'memory'})}><Icon name="hardDrive" size={16}/>Open Memory</button></div>
    </>;
  }
  const category = tx.merchant_category;
  return <>
    <p>This is your decision. TrustLedger never dismisses an alert or moves money for you.</p>
    <div className="choices" role="radiogroup" aria-label="Your decision">
      <button role="radio" disabled={busy || !enabled} aria-checked={choice === 'normal'} className="choice" onClick={() => setChoice('normal')}>
        <Icon name="checkCircle" size={20}/><b>This looks normal</b><span>I recognize this charge.</span></button>
      <button role="radio" disabled={busy || !enabled} aria-checked={choice === 'review'} className="choice" onClick={() => { setChoice('review'); setConsent(false); }}>
        <Icon name="search" size={20}/><b>Needs further review</b><span>I want to look into it.</span></button>
    </div>
    {choice && <div className="consequence" role="group" aria-label="What happens next">
      <h3>What happens next</h3>
      <ul>
        <li><Icon name="check" size={14}/>Your decision is recorded for this alert.</li>
        <li><Icon name="check" size={14}/>{choice === 'normal' ? 'The alert stays in your history; future similar charges are still checked.' : 'The alert stays flagged for you to follow up.'}</li>
        <li><Icon name="check" size={14}/>No money moves and nothing is reported to a bank.</li>
      </ul>
      {choice === 'normal' && <div className="consent">
        <h3>Separate from your decision: memory</h3>
        <label className={'check' + (memoryOff ? ' disabled' : '')}>
          <input type="checkbox" checked={consent} disabled={busy || memoryOff} onChange={e => setConsent(e.target.checked)}/>
          <span><b>Remember this {prettyCategory(category)} preference</b>
            <small>{memoryOff ? 'Memory writes are turned off on this server.' :
              'If checked, only the sentence below is saved. It is stored with Backboard when it is configured, otherwise in the local fallback, and you will see which. Delete it anytime.'}</small></span></label>
        <blockquote className="memtext"><Icon name="hardDrive" size={14}/>{memorySentence(category)}</blockquote>
        <p className="quiet">No merchant name, amount or ID is saved. It adds context to future analyses; it never silences an alert.</p>
      </div>}
      {choice === 'review' && <p className="quiet">Nothing is remembered when you choose review.</p>}
      <div className="actions">
        <button className="primary" disabled={busy || !enabled} onClick={() => void confirm(alert, choice, choice === 'normal' && consent)}>
          {busy ? 'Saving…' : choice === 'normal' ? (consent ? 'Confirm normal and remember' : 'Confirm normal, don’t remember') : 'Confirm needs review'}</button>
        <button onClick={() => { setChoice(null); setConsent(false); }} disabled={busy}>Cancel</button>
      </div>
    </div>}
  </>;
}

/** The case file: one transaction explained in depth, with evidence, optional AI and the human decision. */
export default function Case({id, from}: {id: string; from?: string}) {
  const {transactions, alerts, runs, analyze, memoryKey, loaded, ready, revision, go} = useWorkspace();
  const tx = transactions.find(t => t.id === id);
  const alert = alerts.find(a => a.transaction_id === id);
  const {preview} = usePreview(tx?.id, memoryKey);
  if (!tx) return loaded ? <div className="page"><div className="empty"><Icon name="search" size={24}/>
    <p>That transaction was not found.</p><button onClick={() => go({view: 'activity'})}>Back to Activity</button></div></div>
    : <p className="loading" role="status">Loading…</p>;
  const run = runs[tx.id];
  const backTo = from === 'activity' ? 'Activity' : 'Today';
  return <div className="page case">
    <header className="casehead">
      <button className="back" onClick={() => go({view: from === 'activity' ? 'activity' : 'today'})}><Icon name="arrowLeft" size={15}/>{backTo}</button>
      <span className={'icontile large' + (alert?.status === 'open' ? ' alert' : '')}><Icon name={alert ? alertIcons[alert.alert_type] : categoryIcon(tx.merchant_category)} size={26}/></span>
      <div className="casetitle"><div className="eyebrow">{!ready ? 'Analysis unavailable' : alert ? labels[alert.alert_type] : 'No alert'}</div><h1>{tx.merchant_display}</h1></div>
      <div className="caseamount"><strong>{money(tx.amount)}</strong>{alert && <small>{statusText[alert.status]}</small>}</div>
    </header>
    <aside className="facts" aria-label="Transaction details">
      <dl>
        <div><dt>When</dt><dd>{tx.date_only ? tx.occurred_at.slice(0, 10) + ' (date only)' : fullDate(tx.occurred_at)}</dd></div>
        <div><dt>Category</dt><dd>{prettyCategory(tx.merchant_category)}</dd></div>
        <div><dt>Type</dt><dd>{tx.kind === 'purchase' ? (tx.is_subscription ? 'Recurring subscription' : 'One-time purchase') : tx.kind} · {tx.direction === 'unknown' ? 'Direction unknown' : tx.direction}</dd></div>
        <div><dt>Data source</dt><dd>{tx.source === 'synthetic' ? 'Synthetic fixture' : 'Capital One Nessie sandbox'}</dd></div>
        <div><dt>Reference</dt><dd className="mono">{tx.id}</dd></div>
      </dl>
    </aside>
    <div className="steps">
      <Step n={1} title="Why it was flagged" tag={alert && <Chip tone={alert.severity === 'high' ? 'danger' : 'warn'}>{alert.severity} priority</Chip>}>
        {!ready ? <p>Analysis is unavailable. Refresh before taking action.</p> : alert ? <Evidence alert={alert}/> : <p>No rule was triggered for this charge. It was compared against duplicate, unusual-amount and subscription-increase checks. You can still ask for a plain-language explanation or run an AI second opinion.</p>}
        {ready && alert && <RelevantMemory transactionId={tx.id}/>}
        <ExplanationPanel key={revision} tx={tx}/>
      </Step>
      <Step n={2} title="AI second opinion" tag={<Chip tone="ai" icon="sparkles">Optional</Chip>}>
        <AiStep tx={tx} run={ready ? run : undefined} stale={run?.state === 'done' && run.memoryKey !== memoryKey}
          enabled={ready} fieldCount={preview ? Object.keys(preview.safe_payload).length : null} onRun={() => void analyze(tx.id)}/>
      </Step>
      <Step n={3} title="Your decision">
        {ready && alert ? <Decision alert={alert} tx={tx} enabled={ready}/> : <p>{ready ? 'Nothing to decide: no alert exists for this charge.' : 'Refresh before making a decision.'}</p>}
      </Step>
    </div>
  </div>;
}
