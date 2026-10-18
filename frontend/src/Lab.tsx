import {useState, type ReactNode} from 'react';
import {money, type Movement} from './api';
import {Icon} from './icons';
import {fullDate, prettyCategory} from './lib';
import {Chip} from './ui';

/** How much of a step is real. Shown on every step so a walkthrough is never mistaken for a live operation. */
export type Basis = 'real' | 'guided' | 'mixed';
const basisText: Record<Basis, {label: string; tone: 'good' | 'neutral' | 'ai'}> = {
  real: {label: 'Real backend data', tone: 'good'},
  guided: {label: 'Guided walkthrough · nothing is saved or sent', tone: 'neutral'},
  mixed: {label: 'Real data, guided steps · nothing is saved or sent', tone: 'ai'},
};

export interface LabStep {
  id: string; chapter: string; title: string; basis: Basis;
  inputTitle?: string; input?: ReactNode; processTitle?: string; process?: ReactNode; outputTitle?: string; output?: ReactNode;
  /** Replaces the three panels (the transformation steps use their own three-column view). */
  full?: ReactNode;
  why: {why: string; changed: string; unchanged: string; next: string};
}

/** Input / Process / Output, then why it matters. Back, Next and Restart; progress by chapter. */
export function LabLayout({eyebrow, title, objective, reference, steps, stepId, onStep, onRestart}: {
  eyebrow: string; title: string; objective: string; reference: ReactNode;
  steps: LabStep[]; stepId: string; onStep: (id: string) => void; onRestart: () => void;
}) {
  const found = steps.findIndex(s => s.id === stepId);
  const index = found < 0 ? 0 : found;
  const step = steps[index];
  const chapters = [...new Set(steps.map(s => s.chapter))];
  const basis = basisText[step.basis];
  return <div className="page lab">
    <header className="labhead">
      <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p className="quiet">{objective}</p></div>
      <div className="labref">{reference}</div>
    </header>
    <nav className="labprogress" aria-label="Walkthrough progress">
      {chapters.map(chapter => <div key={chapter} className={'labchapter' + (chapter === step.chapter ? ' current' : '')}>
        <span className="labchaptername">{chapter}</span>
        <ol>{steps.map((s, i) => s.chapter !== chapter ? null : <li key={s.id}>
          <button type="button" aria-label={`Step ${i + 1}: ${s.title}`} aria-current={i === index ? 'step' : undefined}
            className={i < index ? 'done' : i === index ? 'now' : ''} onClick={() => onStep(s.id)}><span>{s.chapter === chapter ? steps.filter(x => x.chapter === chapter).indexOf(s) + 1 : ''}</span></button></li>)}</ol>
      </div>)}
    </nav>
    <section className="labstage" aria-labelledby="lab-step-title" key={step.id}>
      <div className="labsteptop">
        <h2 id="lab-step-title"><span className="labstepno">{index + 1} / {steps.length}</span>{step.title}</h2>
        <Chip tone={basis.tone}>{basis.label}</Chip>
      </div>
      {step.full ? <div className="labfull labpanel">{step.full}</div> : <div className="labpanels">
        <div className="labpanel"><h3>{step.inputTitle ?? 'Input'}</h3>{step.input}</div>
        <div className="labarrow" aria-hidden="true"><Icon name="arrowRight" size={18}/></div>
        <div className="labpanel process"><h3>{step.processTitle ?? 'Process'}</h3>{step.process}</div>
        <div className="labarrow" aria-hidden="true"><Icon name="arrowRight" size={18}/></div>
        <div className="labpanel"><h3>{step.outputTitle ?? 'Output'}</h3>{step.output}</div>
      </div>}
      <dl className="labwhy">
        <div><dt>Why this step exists</dt><dd>{step.why.why}</dd></div>
        <div><dt>What changed</dt><dd>{step.why.changed}</dd></div>
        <div><dt>What did not change</dt><dd>{step.why.unchanged}</dd></div>
        <div><dt>What happens next</dt><dd>{step.why.next}</dd></div>
      </dl>
    </section>
    <footer className="labfoot">
      <button type="button" onClick={() => onStep(steps[index - 1].id)} disabled={index === 0}><Icon name="arrowLeft" size={15}/>Previous</button>
      <button type="button" onClick={onRestart}><Icon name="refresh" size={15}/>Restart journey</button>
      <button type="button" className="primary" onClick={() => onStep(steps[index + 1].id)} disabled={index === steps.length - 1}>Next<Icon name="arrowRight" size={15}/></button>
    </footer>
  </div>;
}

/** A transaction as a card. `hot` highlights the fields a clicked rule condition refers to. */
export function TxnCard({tx, label, hot = [], tone}: {tx: Movement; label?: string; hot?: string[]; tone?: 'flag'}) {
  const row = (key: string, name: string, value: ReactNode) =>
    <div className={'txnrow' + (hot.includes(key) ? ' hot' : '')}><dt>{name}</dt><dd>{value}</dd></div>;
  return <div className={'txncard' + (tone === 'flag' ? ' flag' : '')}>
    {label && <div className="txnlabel">{label}</div>}
    <div className="txnmain"><b>{tx.merchant_display}</b><strong>{money(tx.amount)}</strong></div>
    <small>{prettyCategory(tx.merchant_category)}{tx.is_subscription ? ' · recurring' : ''} · synthetic demo data</small>
    <details className="txnfields">
      <summary>Show every field in this record</summary>
      <dl>
        {row('id', 'Transaction ID', <span className="mono">{tx.id}</span>)}
        {row('merchant', 'Merchant', tx.merchant_display)}
        {row('amount', 'Amount', money(tx.amount))}
        {row('when', 'When', tx.date_only ? tx.occurred_at.slice(0, 10) + ' (date only)' : fullDate(tx.occurred_at))}
        {row('category', 'Category', prettyCategory(tx.merchant_category))}
        {row('direction', 'Direction', tx.direction)}
        {row('account', 'Account token', <span className="mono">{tx.account_token}</span>)}
        {row('source', 'Source', tx.source)}
      </dl>
    </details>
  </div>;
}

export type Verdict = 'removed' | 'generalized' | 'retained' | 'na';
export interface TField {
  key: string; label: string; value: string; verdict: Verdict;
  /** What this field becomes in the output, when it is generalized or retained. */
  becomes?: string; reason: string; exposure: string;
}
const verdictText: Record<Verdict, string> = {removed: 'REMOVED', generalized: 'GENERALIZED', retained: 'RETAINED', na: 'NOT APPLICABLE'};

/** Facts, then minimization, then the output. Data minimization: excluded details are simply not in the outbound content. */
export function FieldTransformation({fields, output, outputTitle, leaves, leftTitle = 'Original financial facts', transformLabel = 'Transform'}: {
  fields: TField[]; output: ReactNode; outputTitle: string; leaves: string; leftTitle?: string; transformLabel?: string;
}) {
  const [done, setDone] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const field = fields.find(f => f.key === picked);
  return <div className="transform">
    <div className="tcols">
      <section aria-label={leftTitle}>
        <h3>{leftTitle}</h3>
        <ul>{fields.map(f => <li key={f.key} className={(done ? 'v-' + f.verdict : '') + (picked === f.key ? ' picked' : '')}>
          <button type="button" aria-pressed={picked === f.key} onClick={() => setPicked(picked === f.key ? null : f.key)}>
            <small>{f.label}</small><b>{f.value}</b></button></li>)}</ul>
      </section>
      <section aria-label="Data minimization" className="engine">
        <h3>Data minimization</h3>
        <ul>{fields.map(f => <li key={f.key} className={(done ? 'v-' + f.verdict : '') + (picked === f.key ? ' picked' : '')}>
          <button type="button" onClick={() => setPicked(picked === f.key ? null : f.key)}>
            <span>{f.label}</span><i className="verdict">{done ? verdictText[f.verdict] : 'examining…'}</i></button></li>)}</ul>
        <div className="tbtn">
          <button type="button" className="primary" onClick={() => setDone(true)} disabled={done}>{transformLabel}</button>
          {done && <button type="button" onClick={() => { setDone(false); setPicked(null); }}><Icon name="refresh" size={14}/>Replay</button>}
        </div>
      </section>
      <section aria-label={outputTitle} className={'result' + (done ? ' shown' : '')}>
        <h3>{outputTitle}</h3>
        <div className="toutput" aria-live="polite">{done ? output : <p className="quiet">Press “{transformLabel}” to see what is produced.</p>}</div>
        {done && <p className="leaves"><b>Leaves TrustLedger:</b> {leaves}</p>}
      </section>
    </div>
    <div className="tdetail" aria-live="polite">
      {field ? <>
        <b>{field.label}: {verdictText[field.verdict].toLowerCase()}</b>
        <span><i>Why:</i> {field.reason}</span>
        <span><i>If it were shared:</i> {field.exposure}</span>
        {field.becomes && <span><i>Becomes:</i> {field.becomes}</span>}
      </> : <span className="quiet">Click any field to see why it is removed, generalized or kept, and what sharing it could expose.</span>}
    </div>
    <p className="tnote"><Icon name="info" size={14}/>This is data minimization, not encryption. Excluded details are not in the outbound content at all, so there is nothing to decrypt. It does not make the event anonymous: a category and a decision still reveal a little behavior.</p>
  </div>;
}
