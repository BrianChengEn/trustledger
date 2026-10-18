import {useState} from 'react';
import {money, labels, type Movement} from './api';
import {Icon} from './icons';
import {FieldTransformation, LabLayout, TxnCard, type LabStep, type TField, type Verdict} from './Lab';
import {exposureByField, memoryFacts} from './labdata';
import {memoryStore, memorySentence} from './lib';
import {localValue} from './PrivacyView';
import {usePreview} from './preview';
import {backboardBody, duplicateChecks, gapText, pickStory, reasonCodes} from './story';
import {Callout, Chip} from './ui';
import {useWorkspace} from './workspace';

type Provider = 'jev' | 'gemini' | 'backboard';
const providers: {key: Provider; name: string; role: string; needs: string}[] = [
  {key: 'jev', name: 'Jev', role: 'Supplementary AI risk analysis.', needs: 'A generalized summary of the charge: eight approved fields.'},
  {key: 'gemini', name: 'Gemini', role: 'Human-readable explanation.', needs: 'The existing alert type and severity, closed reason codes, and the same eight approved fields.'},
  {key: 'backboard', name: 'Backboard Memory', role: 'Consented historical memory.', needs: 'One category-level sentence, and only after you consent.'},
];
const verdictOf = (action: string): Verdict =>
  action === 'dropped' ? 'removed' : action === 'allowed' ? 'retained' : 'generalized';

export default function PrivacyLab({step, onStep}: {step: string; onStep: (id: string) => void}) {
  const {transactions, alerts, memories, memoryKey, runs, go, href} = useWorkspace();
  const story = pickStory(transactions, alerts);
  const [provider, setProvider] = useState<Provider>('jev');
  const [hot, setHot] = useState<string | null>(null);
  const {preview, failed, loading, retry} = usePreview(story?.tx.id, memoryKey);
  if (!story) return <div className="page lab"><div className="empty"><Icon name="search" size={26}/>
    <h2>The walkthrough needs a real flagged transaction.</h2>
    <p>No duplicate alert exists in this dataset, and nothing is invented to fill the gap.</p></div></div>;

  const {tx, alert, twin, category} = story;
  const checks = duplicateChecks(tx, twin);
  const sentence = memorySentence(category);
  const chosen = providers.find(p => p.key === provider)!;
  const run = runs[tx.id];
  const savedMemory = memories.find(m => m.summary === sentence);

  // Fields for the chosen provider, from the backend's real inspection where it exists.
  const modelFields = (preview?.inspection ?? []).map((i): TField => ({
    key: i.field, label: i.field, value: localValue(i.field, tx as Movement), verdict: verdictOf(i.action),
    becomes: i.output !== null && i.output !== undefined ? String(i.output) : undefined,
    reason: i.reason, exposure: exposureByField[i.field] ?? 'Sharing the raw value would reveal more than the provider needs.'}));
  const geminiDoc = preview ? {task: 'explain_existing_alert', alert_type: alert.alert_type, severity: alert.severity,
    needs_human: alert.needs_human, reason_codes: reasonCodes(alert.alert_type, alert.needs_human, preview.safe_payload), features: preview.safe_payload} : null;
  const fields: TField[] = provider === 'backboard' ? memoryFacts(tx, category)
    : provider === 'gemini' ? [...modelFields, {key: 'alert_evidence', label: 'Alert evidence text', value: alert.evidence[0] ?? '', verdict: 'removed',
      reason: 'Only closed reason codes are sent, never free text.', exposure: 'Free text can carry details the structured fields deliberately leave out.'}]
    : modelFields;
  const counts = (v: Verdict) => fields.filter(f => f.verdict === v).length;
  const needsPreview = provider !== 'backboard';
  const outputFor = provider === 'backboard'
    ? <><blockquote className="memtext"><Icon name="hardDrive" size={14}/>{sentence}</blockquote><details><summary>Exact body</summary><pre className="json">{JSON.stringify(backboardBody(category), null, 2)}</pre></details></>
    : <><pre className="json" aria-label="Approved payload">{JSON.stringify(provider === 'gemini' ? geminiDoc : preview?.safe_payload, null, 2)}</pre>
      {provider === 'gemini' && <p className="quiet">Assembled from the documented request schema for this alert. Nothing was sent to Gemini.</p>}</>;
  const insideCount = 8;
  const outsideCount = provider === 'backboard' ? 1 : Object.keys(preview?.safe_payload ?? {}).length;

  const steps: LabStep[] = [
    {id: 'p-1', chapter: 'Privacy walkthrough', title: 'The original data', basis: 'real',
      inputTitle: 'Data inside TrustLedger', input: <TxnCard tx={tx} label="Full record"/>,
      processTitle: 'Stays inside', process: <p>This record lives in TrustLedger’s database. <b>Nothing here is sent to an outside service automatically.</b></p>,
      outputTitle: 'What can leave', output: <p className="quiet">Only what a later step approves, and only when you ask.</p>,
      why: {why: 'Showing the raw record first makes the later removals visible.', changed: 'Nothing yet.', unchanged: 'Nothing has left TrustLedger.', next: 'Why would an outside service be involved at all?'}},
    {id: 'p-2', chapter: 'Privacy walkthrough', title: 'Why an AI service might be asked', basis: 'real',
      inputTitle: 'Earlier charge', input: <TxnCard tx={twin} hot={hot ? [hot] : []}/>,
      processTitle: 'The backend’s rule (click a condition)', process: <><TxnCard tx={tx} hot={hot ? [hot] : []} tone="flag"/>
        <ul className="conditions">{[['merchant', 'Same merchant', checks.merchant], ['amount', 'Same amount', checks.amount], ['when', `Within 24 hours (${gapText(checks.gapMinutes)})`, checks.within24h], ['direction', 'Debit', checks.debit]]
          .map(([k, label, ok]) => <li key={String(k)}><button type="button" aria-pressed={hot === k} className={hot === k ? 'hot' : ''} onClick={() => setHot(hot === k ? null : String(k))}>
            <Icon name={ok ? 'checkCircle' : 'x'} size={16}/>{String(label)}</button></li>)}</ul></>,
      outputTitle: 'Rules alert (no AI used)', output: <><b>{labels[alert.alert_type]}</b><p className="quiet">{alert.severity} severity · human review {alert.needs_human ? 'required' : 'not required'}. Optional AI can add to this; it cannot replace it.</p></>,
      why: {why: 'The deterministic rules flag the charge on the backend, with no AI call.', changed: 'An alert exists.', unchanged: 'No outside service has been contacted.', next: 'Pick which service to look at.'}},
    {id: 'p-3', chapter: 'Privacy walkthrough', title: 'Select an external service', basis: 'guided',
      inputTitle: 'Three different roles', input: <ul className="plain">{providers.map(p => <li key={p.key}><b>{p.name}</b>: {p.role}</li>)}</ul>,
      processTitle: 'Choose one (no request is made)', process: <div className="dests three" role="radiogroup" aria-label="External service">{providers.map(p =>
        <button key={p.key} type="button" role="radio" aria-checked={provider === p.key} aria-pressed={provider === p.key} onClick={() => setProvider(p.key)}>
          <b>{p.name}</b><small>{p.role}</small></button>)}</div>,
      outputTitle: `${chosen.name} needs`, output: <p>{chosen.needs}</p>,
      why: {why: 'Each service has a different job, so each gets different data.', changed: 'Only this walkthrough’s selection.', unchanged: 'No API call, no cost.', next: 'See the transformation for this service.'}},
    {id: 'p-4', chapter: 'Privacy walkthrough', title: `Privacy transformation for ${chosen.name}`, basis: 'mixed',
      full: needsPreview && loading ? <p className="loading" role="status">Loading the real payload from the backend…</p>
        : needsPreview && failed ? <Callout tone="warn" icon="alertTriangle" title="Could not load the real payload" role="alert">Nothing is shown rather than guessing. <button onClick={retry}>Retry</button></Callout>
        : <FieldTransformation key={provider} fields={fields} outputTitle="Approved payload" transformLabel="Transform into approved payload"
          leaves={provider === 'backboard' ? 'one category-level sentence.' : `${outsideCount} generalized fields${provider === 'gemini' ? ' plus closed reason codes' : ''}.`}
          leftTitle="Original internal data" output={outputFor}/>,
      why: {why: 'Every field is either dropped, generalized or kept for a stated reason.', changed: 'Raw values become buckets, labels or nothing.', unchanged: 'The original record stays in TrustLedger.', next: 'See where the boundary is.'}},
    {id: 'p-5', chapter: 'Privacy walkthrough', title: 'The privacy boundary', basis: 'mixed',
      full: <div className="boundary">
        <section><h3>Inside TrustLedger</h3><ul className="plain">{['Transaction ID', 'Merchant', 'Exact amount', 'Exact time', 'Account token', 'Category', 'Direction', 'Your decision'].map(x => <li key={x}>{x}</li>)}</ul>
          <small className="quiet">{insideCount} facts about this charge</small></section>
        <div className="gate" aria-hidden="true"><span>TrustLedger backend</span><Icon name="arrowRight" size={20}/><b>Privacy transformation</b><Icon name="arrowRight" size={20}/><span>Approved data</span></div>
        <section className="outside"><h3>Outside: {chosen.name}</h3>
          {provider === 'backboard' ? <ul className="plain"><li>One sentence about a category and a confirmed decision</li></ul>
            : <ul className="plain">{Object.entries(preview?.safe_payload ?? {}).map(([k, v]) => <li key={k}><span className="mono">{k}</span> {String(v)}</li>)}{provider === 'gemini' && <li>Closed reason codes</li>}</ul>}
          <small className="quiet">{outsideCount} {provider === 'backboard' ? 'item' : 'fields'} cross the boundary</small></section>
        <p className="tnote"><Icon name="info" size={14}/>This happens before the outbound request. The excluded fields are simply not included. Encrypting the connection (HTTPS) is a separate protection and is not what removes these fields.</p></div>,
      why: {why: 'The boundary makes the amount of exposed data visible.', changed: 'Only the approved data crosses it.', unchanged: 'The full record never does.', next: 'What can the service do with it?'}},
    {id: 'p-6', chapter: 'Privacy walkthrough', title: 'What the provider can do', basis: 'mixed',
      inputTitle: 'Approved payload', input: <p>{chosen.needs}</p>,
      processTitle: chosen.name, process: <p>{provider === 'jev' ? 'May return supplementary analysis of the generalized fields.'
        : provider === 'gemini' ? 'May explain the existing alert in plain language. It does not decide fraud.' : 'May store the consented memory event.'}</p>,
      outputTitle: 'Status of each kind of result', output: <ul className="plain">
        <li><Chip>Payload preview</Chip> always available here, from the backend’s serializer.</li>
        <li>{provider === 'jev' && run?.state === 'done'
          ? <><Chip tone={run.result.provider_mode === 'rules+jev-live' ? 'ai' : 'neutral'}>{run.result.provider_mode === 'rules+jev-live' ? 'Live Jev response' : run.result.provider_mode === 'degraded' ? 'AI unavailable, rules shown' : 'Rules-only'}</Chip> from your earlier request this session.</>
          : provider === 'backboard' && savedMemory ? <><Chip tone={memoryStore(savedMemory.source).tone}>{memoryStore(savedMemory.source).label}</Chip> your saved memory.</>
          : <><Chip>No saved result</Chip> nothing has been requested for this charge.</>}</li>
        <li className="quiet">This walkthrough never makes a live request and never invents a response.</li></ul>,
      why: {why: 'A payload preview is not a provider result.', changed: 'Nothing.', unchanged: 'No request was made.', next: 'The takeaway.'}},
    {id: 'p-7', chapter: 'Privacy walkthrough', title: 'The privacy takeaway', basis: 'mixed',
      full: <div className="takeaway">
        <section><h3>Original transaction</h3><TxnCard tx={tx}/></section>
        <section className="after"><h3>Approved payload ({chosen.name})</h3>{outputFor}</section>
        <ul className="tally"><li><b>{counts('removed')}</b> removed</li><li><b>{counts('generalized')}</b> generalized</li><li><b>{counts('retained')}</b> kept</li></ul>
        <blockquote className="lesson">TrustLedger limits what external AI services receive before the request leaves the backend.</blockquote>
        <p className="quiet">This reduces what a provider can see. It does not remove every privacy risk.</p>
        <div className="actions"><button type="button" className="primary" onClick={() => go({view: 'memory', lab: ''})}>See How Memory Works<Icon name="arrowRight" size={15}/></button>
          <a className="button" href={href({view: 'privacy', tx: tx.id})}>Open the real privacy inspector</a></div></div>,
      why: {why: 'Compare what exists with what is allowed out.', changed: 'Nothing.', unchanged: 'Your data and decisions.', next: 'Try the Memory Lab with the same charge.'}},
  ];
  void money;
  const idOf = (t: string) => steps.some(s => s.id === t) ? t : steps[0].id;
  return <LabLayout eyebrow="Privacy Lab" title="How TrustLedger uses outside AI without sharing the full transaction."
    objective="See, field by field, what is removed, generalized and kept before any request leaves the backend."
    reference={<><Chip icon="database">Demo story: {tx.merchant_display} · {money(tx.amount)} · <span className="mono">{tx.id}</span></Chip>
      <small className="quiet">Owner demo-user-001 · synthetic fixture · same charge as the Memory Lab</small></>}
    steps={steps} stepId={idOf(step)} onStep={onStep} onRestart={() => { setHot(null); setProvider('jev'); onStep(steps[0].id); }}/>;
}
