import {useState} from 'react';
import {money, type Alert} from './api';
import {Icon} from './icons';
import {fullDate, memoryCategory, memoryModeCopy, memorySentence, memoryStore, prettyCategory} from './lib';
import {FieldTransformation, LabLayout, TxnCard, type LabStep} from './Lab';
import {memoryFacts} from './labdata';
import {RelevantResult} from './RelevantMemoryCard';
import {relevantView, useRelevantMemories} from './relevant';
import {backboardBody, duplicateChecks, gapText, pickStory, type DuplicateChecks} from './story';
import {Callout, Chip} from './ui';
import {useWorkspace} from './workspace';
import {labels} from './api';

const CH1 = 'Level 1 · Create a memory', CH2 = 'Level 2 · Use a memory';

/** What the rule found, as the four checkable conditions. Clicking one highlights the matching values. */
function Conditions({checks, hot, onHot}: {checks: DuplicateChecks; hot: string | null; onHot: (k: string | null) => void}) {
  const rows: {key: string; label: string; ok: boolean; detail: string}[] = [
    {key: 'merchant', label: 'Same merchant', ok: checks.merchant, detail: 'merchant'},
    {key: 'amount', label: 'Same amount', ok: checks.amount, detail: 'amount'},
    {key: 'when', label: `Within 24 hours (${gapText(checks.gapMinutes)} apart)`, ok: checks.within24h, detail: 'when'},
    {key: 'direction', label: 'Debit', ok: checks.debit, detail: 'direction'},
  ];
  return <ul className="conditions">{rows.map(r => <li key={r.key}>
    <button type="button" aria-pressed={hot === r.key} className={hot === r.key ? 'hot' : ''} onClick={() => onHot(hot === r.key ? null : r.key)}>
      <Icon name={r.ok ? 'checkCircle' : 'x'} size={16}/>{r.label}</button></li>)}</ul>;
}

function AlertBox({alert, extra}: {alert: Alert; extra?: string}) {
  return <div className="alertbox">
    <b>{labels[alert.alert_type]}</b>
    <dl><div><dt>Severity</dt><dd>{alert.severity}</dd></div><div><dt>Human review</dt><dd>{alert.needs_human ? 'required' : 'not required'}</dd></div></dl>
    <ul className="evidence">{alert.evidence.map(e => <li key={e}><Icon name="search" size={14}/><span>{e}</span></li>)}</ul>
    {extra && <small className="quiet">{extra}</small>}
  </div>;
}

export default function MemoryLab({step, onStep}: {step: string; onStep: (id: string) => void}) {
  const {transactions, alerts, memories, health, go, href} = useWorkspace();
  const story = pickStory(transactions, alerts);
  const [hot, setHot] = useState<string | null>(null);
  const [choice, setChoice] = useState<'normal' | 'review'>('normal');
  const [consent, setConsent] = useState(false);
  const [dest, setDest] = useState<'sqlite' | 'backboard' | null>(null);
  const [deleted, setDeleted] = useState(false);
  const later = story?.later ?? null;
  // Read-only GET of the real result for the later transaction (no write, no AI, no paid call).
  const real = useRelevantMemories(later?.tx.id, !!later);
  if (!story) return <div className="page lab"><div className="empty"><Icon name="search" size={26}/>
    <h2>The walkthrough needs a real duplicate alert.</h2>
    <p>None of the transactions in this dataset triggers the duplicate rule. Nothing is invented to fill the gap. Add two matching charges as an admin, or use the Level 2 demo database.</p></div></div>;

  const {tx, alert, twin, category} = story;
  const sentence = memorySentence(category);
  const savedForCategory = memories.filter(m => memoryCategory(m.summary) === category);
  const saved = savedForCategory[0];
  const checks = duplicateChecks(tx, twin);
  const laterChecks = later ? duplicateChecks(later.tx, tx) : null;
  const target = later?.tx ?? tx;
  const targetAlert = later?.alert ?? alert;
  const memMode = memoryModeCopy(health?.memory_mode);
  const hotKeys = hot ? [hot] : [];

  const facts = memoryFacts(tx, category);

  const steps: LabStep[] = [
    {id: 'l1-1', chapter: CH1, title: 'The original transaction', basis: 'real',
      inputTitle: 'Original transaction', input: <TxnCard tx={tx} label="Full record"/>,
      processTitle: 'Inside TrustLedger', process: <ol className="pipeline"><li>Record arrives in the local database</li><li>Local rules engine reads it</li><li>An alert is raised, or not</li></ol>,
      outputTitle: 'Result', output: <><Chip tone="good" icon="check">Transaction received</Chip><p className="quiet">The full record stays inside TrustLedger’s backend.</p></>,
      why: {why: 'TrustLedger first sees the full transaction, inside its own backend.', changed: 'The transaction is now part of the user’s history.',
        unchanged: 'Nothing has left TrustLedger.', next: 'The deterministic rules check it against earlier charges.'}},
    {id: 'l1-2', chapter: CH1, title: 'Why the alert triggered', basis: 'real',
      inputTitle: 'Earlier transaction', input: <TxnCard tx={twin} label="Earlier charge" hot={hotKeys}/>,
      processTitle: 'The duplicate rule (click a condition)', process: <>
        <TxnCard tx={tx} label="Suspicious charge" hot={hotKeys} tone="flag"/>
        <Conditions checks={checks} hot={hot} onHot={setHot}/></>,
      outputTitle: 'Actual rule output', output: <AlertBox alert={alert} extra={`Gap between the two charges: ${gapText(checks.gapMinutes)}.`}/>,
      why: {why: 'A deterministic backend rule found a repeated debit pattern.', changed: 'An alert now exists and needs a person.', unchanged: 'No AI was used. This is the rules engine.',
        next: 'You decide whether this is a real problem.'}},
    {id: 'l1-3', chapter: CH1, title: 'Your decision', basis: 'guided',
      inputTitle: 'Flagged transaction', input: <TxnCard tx={tx} tone="flag"/>,
      processTitle: 'Your review choices', process: <div className="choices" role="radiogroup" aria-label="Walkthrough review choice">
        <button type="button" role="radio" aria-checked={choice === 'normal'} className="choice" onClick={() => setChoice('normal')}><Icon name="checkCircle" size={20}/><b>This looks normal</b><span>I recognize this charge.</span></button>
        <button type="button" role="radio" aria-checked={choice === 'review'} className="choice" onClick={() => { setChoice('review'); setConsent(false); }}><Icon name="search" size={20}/><b>Needs further review</b><span>I want to look into it.</span></button></div>,
      outputTitle: 'Decision', output: <><Chip tone={choice === 'normal' ? 'good' : 'warn'}>{choice === 'normal' ? 'Decision: Normal' : 'Decision: Needs review'}</Chip>
        <p className="quiet">{choice === 'normal' ? 'A normal decision becomes eligible for optional memory.' : 'A review decision never creates a memory.'}</p></>,
      why: {why: 'Rules find risk, but a person decides whether this specific alert is legitimate.', changed: 'Walkthrough only: no decision is submitted.',
        unchanged: 'Your real alert is still open. Nothing was recorded.', next: 'Saving a memory needs separate, explicit consent.'}},
    {id: 'l1-4', chapter: CH1, title: 'Explicit consent', basis: 'guided',
      inputTitle: 'Your normal decision', input: <Chip tone="good">Decision: Normal</Chip>,
      processTitle: 'The consent checkbox (starts unchecked)', process: <label className="check">
        <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>
        <span><b>Remember this decision</b><small>Unchecked by default. Toggle it to compare the outcomes.</small></span></label>,
      outputTitle: 'Outcome', output: consent
        ? <Callout tone="good" icon="check" title="Eligible for a privacy-safe memory">A minimal event may be created, if the server allows memory writes (ALLOW_MEMORY_WRITE) and the decision is normal.</Callout>
        : <Callout tone="neutral" icon="eyeOff" title="No memory is written">Your decision is recorded in the app. Nothing is sent to Backboard.</Callout>,
      why: {why: 'Confirming an alert is normal is not permission to store that decision outside the app.', changed: 'Only the consent choice differs between the two outcomes.',
        unchanged: 'The decision itself and the alert are the same either way.', next: consent ? 'The full record is reduced to a minimal event.' : 'Toggle consent on to continue the story.'}},
    {id: 'l1-5', chapter: CH1, title: 'From facts to a memory event', basis: 'guided',
      full: <FieldTransformation fields={facts} outputTitle="Minimal memory event" transformLabel="Transform into Memory Event"
        leaves="the category and the confirmed-normal decision, as one sentence."
        output={<><blockquote className="memtext"><Icon name="hardDrive" size={14}/>{sentence}</blockquote>
          <details><summary>Exact body for Backboard</summary><pre className="json">{JSON.stringify(backboardBody(category), null, 2)}</pre></details></>}/>,
      why: {why: 'The external memory service does not need the full transaction to keep useful context.', changed: 'Four fields are dropped; two facts remain, as one sentence.',
        unchanged: 'The original record is untouched in TrustLedger’s database.', next: 'The sentence is stored in two different places, for different reasons.'}},
    {id: 'l1-6', chapter: CH1, title: 'Where the data goes', basis: 'guided',
      inputTitle: 'Original record', input: <TxnCard tx={tx}/>,
      processTitle: 'Two destinations (click one)', process: <div className="dests">
        <button type="button" aria-pressed={dest === 'sqlite'} onClick={() => setDest(dest === 'sqlite' ? null : 'sqlite')}><Icon name="database" size={18}/><b>SQLite</b><small>this server</small></button>
        <button type="button" aria-pressed={dest === 'backboard'} onClick={() => setDest(dest === 'backboard' ? null : 'backboard')}><Icon name="hardDrive" size={18}/><b>Backboard memory</b><small>external</small></button></div>,
      outputTitle: dest === 'backboard' ? 'Stored by Backboard' : dest === 'sqlite' ? 'Stored in SQLite' : 'What each stores', output: dest === 'backboard'
        ? <><p>Only the approved sentence.</p><pre className="json">{JSON.stringify(backboardBody(category), null, 2)}</pre><p className="quiet">Sent only when a Backboard key is configured and you consented. Here: <b>{memMode.label}</b>.</p></>
        : dest === 'sqlite' ? <ul className="plain"><li>The structured transaction (merchant, amount, account, ID).</li><li>Your decision and consent.</li><li>The local memory record: id, sentence, source.</li></ul>
        : <p className="quiet">Click SQLite or Backboard to see what each one holds.</p>,
      why: {why: 'The app needs detailed records to work; the memory provider only needs limited context.', changed: 'Detail stays local; the minimal sentence is the only thing a provider receives.',
        unchanged: 'Backboard never receives the full transaction.', next: 'See the resulting memory.'}},
    {id: 'l1-7', chapter: CH1, title: 'The memory result', basis: saved ? 'mixed' : 'guided',
      inputTitle: 'Approved event', input: <blockquote className="memtext"><Icon name="hardDrive" size={14}/>{sentence}</blockquote>,
      processTitle: 'The memory write', process: <p className="quiet">A real write happens only through the Case page, with the consent checkbox ticked. This walkthrough never writes.</p>,
      outputTitle: 'Resulting memory card', output: <>
        <div className="memcard preview"><Chip>Preview only</Chip><blockquote>{sentence}</blockquote><small>Category: {prettyCategory(category)} · nothing was saved by this walkthrough</small></div>
        {saved && <div className="memcard"><Chip tone={memoryStore(saved.source).tone}>{memoryStore(saved.source).label}</Chip><blockquote>{saved.summary}</blockquote>
          <small>Your real memory · saved {fullDate(saved.created_at)}</small></div>}
        <div className="actions"><a className="button" href={href({view: 'case', tx: tx.id, from: 'today'})}>Open the real case</a><a className="button" href={href({view: 'memory'})}>My Memories</a></div></>,
      why: {why: 'The memory keeps context you consented to.', changed: 'A future alert in the same category can find this context.', unchanged: 'The original transaction is not stored at the memory provider.',
        next: 'Level 2: how a later alert uses it.'}},

    {id: 'l2-1', chapter: CH2, title: 'A new transaction arrives', basis: later ? 'real' : 'guided',
      inputTitle: 'Earlier transaction', input: <TxnCard tx={tx} label="Earlier charge (you confirmed it)"/>,
      processTitle: 'Compared with the new one', process: later ? <TxnCard tx={later.tx} label="New charge" tone="flag"/>
        : <p className="quiet">The new, similar charge is not in this dataset (it is <span className="mono">txn_syn_009</span> in the separate Level 2 database). Nothing is made up here; the next steps explain the same logic on the charge above.</p>,
      outputTitle: 'How they relate', output: laterChecks
        ? <p>Same merchant: <b>{laterChecks.merchant ? 'yes' : 'no'}</b>. Same amount: <b>{laterChecks.amount ? 'yes' : 'no'}</b>. Apart by <b>{gapText(laterChecks.gapMinutes)}</b>.</p>
        : <p className="quiet">Guided: a later charge from the same merchant and category.</p>,
      why: {why: 'A new transaction is always evaluated on its own.', changed: 'A new charge exists beside the one you confirmed.', unchanged: 'Your earlier decision is not applied to it.', next: 'The rules run again.'}},
    {id: 'l2-2', chapter: CH2, title: 'The fraud rules run again', basis: later ? 'real' : 'mixed',
      inputTitle: 'New transaction', input: <TxnCard tx={target} tone="flag"/>,
      processTitle: 'The same duplicate rule', process: <Conditions checks={laterChecks ?? checks} hot={hot} onHot={setHot}/>,
      outputTitle: 'Actual rule output', output: <AlertBox alert={targetAlert}/>,
      why: {why: 'A past confirmation does not turn fraud detection off.', changed: 'The new charge gets its own alert.', unchanged: 'The rules do not read your memory to decide.', next: 'Memory is looked up by category.'}},
    {id: 'l2-3', chapter: CH2, title: 'Find the category', basis: later ? 'real' : 'mixed',
      inputTitle: 'New transaction', input: <TxnCard tx={target} hot={['category']}/>,
      processTitle: 'Extract the category', process: <p className="bigcat">{prettyCategory(target.merchant_category)}</p>,
      outputTitle: 'Lookup criterion', output: <><p>Category = <b>{prettyCategory(target.merchant_category)}</b></p><p className="quiet">Category matching. Not semantic similarity, and no similarity score exists.</p></>,
      why: {why: 'The current implementation looks for consented memories in the same category.', changed: 'The category becomes the lookup key.', unchanged: 'No full histories are compared.', next: 'The backend checks eligible memories.'}},
    {id: 'l2-4', chapter: CH2, title: 'Local candidate match', basis: saved ? 'real' : 'guided',
      inputTitle: 'Requirements', input: <ul className="plain"><li>Same backend owner</li><li>Previously confirmed normal</li><li>Explicit consent</li><li>Same category</li></ul>,
      processTitle: 'Candidate memory', process: saved
        ? <div className="memcard"><Chip tone={memoryStore(saved.source).tone}>{memoryStore(saved.source).label}</Chip><blockquote>{saved.summary}</blockquote></div>
        : <div className="memcard preview"><Chip>Example only</Chip><blockquote>{sentence}</blockquote><small>You have no saved {prettyCategory(category)} memory yet. Save one from the real case, then this shows your real memory.</small></div>,
      outputTitle: 'Why it is relevant', output: <p>The category matches. That does <b>not</b> mean the merchant or the fraud pattern is the same.</p>,
      why: {why: 'Only memories you consented to, for this owner and category, can be candidates.', changed: 'A candidate memory is identified.', unchanged: 'The alert is untouched.', next: 'The backend verifies it still exists.'}},
    {id: 'l2-5', chapter: CH2, title: 'Backboard verification', basis: later && saved ? 'real' : 'guided',
      inputTitle: 'Memory to check', input: <p className="mono">{saved ? saved.memory_id : 'mem_… (example)'}</p>,
      processTitle: 'The check', process: <p>The backend reads that specific memory from Backboard and compares its text. This is a remote read, <b>not</b> a search and not a similarity score. Without a Backboard key it reports the local copy as local only.</p>,
      outputTitle: later && saved ? 'Real result (read-only)' : 'Illustrative result', output: later && saved
        ? <RelevantResult view={real.view} retry={real.retry}/>
        : <RelevantResult view={relevantView({memories: [{memory_id: 'example', summary: sentence, source: 'local-fallback', created_at: new Date().toISOString(), verification: 'local_only'}], retrieval_mode: 'local_fallback', checked_at: null, failure: null}, false)}/>,
      why: {why: 'It confirms the saved memory is still there and unchanged.', changed: 'The memory is shown with its true verification state.', unchanged: 'An empty list always means “No relevant memory found”.', next: 'See what memory changes about the alert.'}},
    {id: 'l2-6', chapter: CH2, title: 'What memory changes', basis: later ? 'real' : 'mixed',
      full: <div className="beforeafter">
        <section><h3>Without memory</h3><dl><div><dt>Alert</dt><dd>{labels[targetAlert.alert_type]}</dd></div><div><dt>Severity</dt><dd>{targetAlert.severity}</dd></div>
          <div><dt>Human review</dt><dd>{targetAlert.needs_human ? 'required' : 'not required'}</dd></div><div><dt>Historical context</dt><dd>none</dd></div></dl></section>
        <section className="after"><h3>With memory</h3><dl><div><dt>Alert</dt><dd>{labels[targetAlert.alert_type]}</dd></div><div><dt>Severity</dt><dd>{targetAlert.severity}</dd></div>
          <div><dt>Human review</dt><dd>{targetAlert.needs_human ? 'required' : 'not required'}</dd></div><div className="diff"><dt>Historical context</dt><dd><b>available</b></dd></div></dl></section>
        <p className="tnote"><Icon name="info" size={14}/>Only one thing differs. The alert, severity and review requirement are exactly the same. The transaction is not approved and no risk score is lowered.</p></div>,
      why: {why: 'Memory gives you context, not decision authority.', changed: 'Prior consented context is available to read.', unchanged: 'Alert type, severity and human review.', next: 'You stay in control: delete the memory.'}},
    {id: 'l2-7', chapter: CH2, title: 'Delete the memory', basis: 'guided',
      inputTitle: 'The saved memory', input: <div className={'memcard' + (deleted ? ' gone' : '')}><blockquote>{saved ? saved.summary : sentence}</blockquote></div>,
      processTitle: 'Walkthrough delete', process: <><button type="button" disabled={deleted} onClick={() => setDeleted(true)}><Icon name="trash" size={15}/>Delete (walkthrough only)</button>
        {deleted && <button type="button" onClick={() => setDeleted(false)}>Undo</button>}
        <p className="quiet">This does not call the real delete. Use My Memories for the real one.</p></>,
      outputTitle: deleted ? 'A fresh check' : 'Before deleting', output: deleted
        ? <><p><b>Memory removed.</b></p><p><b>No relevant memory found.</b></p><p className="quiet">The alert is still {labels[targetAlert.alert_type].toLowerCase()}, {targetAlert.severity}, human review {targetAlert.needs_human ? 'required' : 'not required'}.</p></>
        : <p className="quiet">Press delete to see the consequence.</p>,
      why: {why: 'You control what the system is allowed to remember.', changed: 'The context is gone for future alerts.', unchanged: 'The fraud alert is the same.', next: 'Compare the three states.'}},
    {id: 'l2-8', chapter: CH2, title: 'Final comparison', basis: 'guided',
      full: <div className="threestates">
        <section><h3>Before memory</h3><p>Rules still work.</p><p className="quiet">No prior context.</p></section>
        <section className="after"><h3>After memory</h3><p>Rules still work.</p><p className="quiet">Prior consented context appears.</p></section>
        <section><h3>After deletion</h3><p>Rules still work.</p><p className="quiet">Prior context is gone.</p></section>
        <blockquote className="lesson">Memory changes what the user knows, not what the fraud rules decide.</blockquote>
        <div className="actions"><button type="button" className="primary" onClick={() => go({view: 'privacy', lab: ''})}>Explore Privacy Protection<Icon name="arrowRight" size={15}/></button>
          <a className="button" href={href({view: 'case', tx: target.id, from: 'today'})}>Open the real case</a></div></div>,
      why: {why: 'This is the one idea to remember.', changed: 'Only the context the user can see.', unchanged: 'Every fraud decision.', next: 'See how Privacy limits what AI receives.'}},
  ];
  const idOf = (t: string) => steps.some(s => s.id === t) ? t : steps[0].id;
  return <LabLayout eyebrow="Memory Lab" title="How a transaction becomes a memory, and how a memory helps."
    objective="Follow one real charge from a flagged alert to a minimal, consented memory, and see what it does for a later one."
    reference={<>
      <Chip icon="database">Demo story: {tx.merchant_display} · {money(tx.amount)} · <span className="mono">{tx.id}</span></Chip>
      <small className="quiet">Owner demo-user-001 · synthetic fixture · rule: duplicate</small></>}
    steps={steps} stepId={idOf(step)} onStep={onStep} onRestart={() => { setHot(null); setChoice('normal'); setConsent(false); setDest(null); setDeleted(false); onStep(steps[0].id); }}/>;
}
