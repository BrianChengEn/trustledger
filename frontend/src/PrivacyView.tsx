import {useState} from 'react';
import {money, type PrivacyPreview, type Movement} from './api';
import {Icon, type IconName} from './icons';
import {fullDate, prettyCategory} from './lib';
import {usePreview} from './preview';
import {Callout, PageHead} from './ui';
import {useWorkspace} from './workspace';

const actionMeta: Record<string, {icon: IconName; verb: string}> = {
  dropped: {icon: 'eyeOff', verb: 'Removed'}, bucketed: {icon: 'layers', verb: 'Bucketed'},
  generalized: {icon: 'tag', verb: 'Generalized'}, tokenized: {icon: 'lock', verb: 'Tokenized'}, allowed: {icon: 'checkCircle', verb: 'Allowed'},
};
// Which safe_payload key each inspected field becomes, so hovering one highlights the other.
const payloadKey: Record<string, string> = {
  merchant_category: 'merchant_category', amount: 'amount_bucket', occurred_at: 'local_day_part',
  prior_user_confirmation: 'prior_user_confirmation',
};
// Local side of each row: what the app holds. Labels describe local data; shared values come only from the backend.
function localValue(field: string, tx: Movement): string {
  switch (field) {
    case 'id / account_token': return `${tx.id} · ${tx.account_token}`;
    case 'merchant_display': return tx.merchant_display;
    case 'merchant_category': return prettyCategory(tx.merchant_category);
    case 'amount': return money(tx.amount);
    case 'occurred_at': return tx.date_only ? tx.occurred_at.slice(0, 10) + ' (date only)' : fullDate(tx.occurred_at);
    case 'prior_user_confirmation': return 'Your saved, consented confirmations';
    default: return 'Anything else, including API keys';
  }
}
const readable = (v: unknown) => typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v);

function Inspector({preview, tx}: {preview: PrivacyPreview; tx: Movement}) {
  const [active, setActive] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const payload = Object.entries(preview.safe_payload);
  const withheld = preview.inspection.filter(i => i.action === 'dropped').length;
  return <div className="privgrid">
    <section className="panel flowpanel" aria-labelledby="flow-title">
      <h2 id="flow-title">From your data to the AI request</h2>
      <div className="flowhead" aria-hidden="true"><span>What TrustLedger knows</span><span>What happens</span><span>What AI would receive</span></div>
      <ul className="flow">
        {preview.inspection.map(i => {
          const meta = actionMeta[i.action] ?? {icon: 'circle' as IconName, verb: i.action};
          const key = payloadKey[i.field];
          return <li key={i.field} className={'flowrow action-' + i.action + (active && key === active ? ' lit' : '')} tabIndex={0}
            onMouseEnter={() => setActive(key ?? null)} onMouseLeave={() => setActive(null)}
            onFocus={() => setActive(key ?? null)} onBlur={() => setActive(null)}>
            <div className="local"><small>{i.field}</small><b>{localValue(i.field, tx)}</b></div>
            <div className="verb"><span className="icontile small"><Icon name={meta.icon} size={14}/></span><span>{meta.verb}<small>{i.reason}</small></span></div>
            <div className="shared">{i.output !== null && i.output !== undefined ? <b>{readable(i.output)}</b> : <i>nothing sent</i>}</div>
          </li>;
        })}
      </ul>
    </section>
    <div className="privside">
    <div className="privstats" aria-label="Summary">
      <div><strong>{payload.length}</strong><span>fields can be shared</span></div>
      <div><strong>{withheld}</strong><span>kinds of data withheld</span></div>
      <div><strong>1</strong><span>destination: {preview.destination}</span></div>
    </div>
    <section className="panel payloadpanel" aria-labelledby="payload-title">
      <div className="sectiontop"><h2 id="payload-title">The complete payload</h2>
        <button aria-pressed={raw} onClick={() => setRaw(r => !r)}>{raw ? 'Show as fields' : 'Show raw JSON'}</button></div>
      <p className="quiet">This is the backend serializer’s output ({preview.schema_version}). The AI receives these {payload.length} fields and nothing else.</p>
      {raw ? <pre className="json" aria-label="Raw safe payload">{JSON.stringify(preview.safe_payload, null, 2)}</pre>
        : <dl className="payload">{payload.map(([k, v]) =>
          <div key={k} className={active === k ? 'lit' : ''}><dt>{k}</dt><dd>{readable(v)}</dd></div>)}</dl>}
    </section>
    </div>
  </div>;
}

/** Privacy answers: what does the app know versus what the AI could actually receive. */
export default function PrivacyView({txId}: {txId?: string}) {
  const {transactions, alerts, memoryKey, go} = useWorkspace();
  const fallback = alerts.find(a => a.status === 'open')?.transaction_id ?? transactions[0]?.id;
  const id = txId && transactions.some(t => t.id === txId) ? txId : fallback;
  const tx = transactions.find(t => t.id === id);
  const {preview, failed, loading, retry} = usePreview(id, memoryKey);
  return <div className="page privacy">
    <PageHead eyebrow="Privacy Inspector" title="What AI actually sees.">
      Your transactions are never sent to AI as they are. Pick a charge to see the real, generalized request the backend would build.</PageHead>
    <div className="privtop">
    <Callout icon="lock" title="Viewing this page sends nothing.">
      Jev runs only when you press Analyze with Jev. An explanation runs only when you press Explain this alert. Neither call receives the raw transaction.</Callout>
    <div className="pick">
      <label htmlFor="priv-tx">Transaction</label>
      <select id="priv-tx" value={id ?? ''} onChange={e => go({view: 'privacy', tx: e.target.value})}>
        {transactions.map(t => <option key={t.id} value={t.id}>{t.merchant_display} · {money(t.amount)} · {t.id}</option>)}
      </select>
      {id && alerts.some(a => a.transaction_id === id) && <button onClick={() => go({view: 'case', tx: id, from: 'today'})}>Open this case<Icon name="arrowRight" size={15}/></button>}
    </div>
    </div>
    {loading && <p className="loading" role="status">Loading the real payload from the backend…</p>}
    {failed && <Callout tone="warn" icon="alertTriangle" title="Could not load the privacy preview" role="alert">
      Nothing is shown rather than guessing. <button onClick={retry}>Retry</button></Callout>}
    {preview && tx && <Inspector key={preview.transaction_id} preview={preview} tx={tx}/>}
  </div>;
}
