import {useState} from 'react';
import {Icon} from '../icons';
import {go} from '../route';
import {Chip} from '../ui';
import {useAuth} from '../auth';
import {useWorkspace} from '../workspace';
import {DotMatrix} from './charts';
import {BUDGET, HEADLINE, TEST_FRAUD, TEST_ROWS, model, outcomeAt, rowAtRank} from './data';

type Metric = 'precision' | 'ap' | 'fp';

/** First screen: the strongest verified result, one metric at a time, then where this research sits in TrustLedger. */
export default function Overview() {
  const m = model(HEADLINE), o = outcomeAt(m, BUDGET);
  const [metric, setMetric] = useState<Metric>('precision');
  const [picked, setPicked] = useState<number | null>(1);
  const fraud = new Set(m.fraud_ranks);
  const row = picked ? rowAtRank(picked) : undefined;
  const {alerts} = useWorkspace();
  const {session} = useAuth();
  const caseId = alerts[0]?.transaction_id;
  const metrics: Record<Metric, {label: string; value: string; text: string}> = {
    precision: {label: 'Precision at 919 alerts', value: `${(o.precision * 100).toFixed(1)}%`,
      text: `Of the ${BUDGET} highest-scored transactions, ${o.tp} were ground-truth fraud. A review team with room for ${BUDGET} alerts spends almost all of it on real cases.`},
    ap: {label: 'Average precision', value: m.average_precision.toFixed(4),
      text: 'How well fraud is ranked above legitimate transactions across every possible cut-off. It matters because fraud is rare, so accuracy says little.'},
    fp: {label: 'False alarms in the 919', value: String(o.fp),
      text: `Legitimate transactions among the ${BUDGET} alerts. Each one costs investigation time and may disturb a real customer.`},
  };
  const cur = metrics[metric];
  return <section aria-labelledby="fl-title" className="fl-overview">
    <h2 id="fl-title" className="visually-hidden">Overview</h2>
    <div className="fl-hero">
      <div className="fl-herotext">
        <p className="fl-lede">From a held-out test slice of {TEST_ROWS.toLocaleString()} BankSim transactions to a {BUDGET}-alert review queue.</p>
        <div className="fl-metrictabs" role="group" aria-label="Headline metric">
          {(Object.keys(metrics) as Metric[]).map(k => <button key={k} type="button" aria-pressed={metric === k} onClick={() => setMetric(k)}>{metrics[k].label}</button>)}
        </div>
        <div className="fl-bignum" aria-live="polite"><strong>{cur.value}</strong><span>{cur.label}</span></div>
        <p>{cur.text}</p>
        <p className="quiet">Offline evaluation on synthetic BankSim data, test steps 150–179 (which earlier experiments had already inspected). It is not a measure of real-bank performance.</p>
        <div className="actions">
          <button type="button" className="primary" onClick={() => go({view: 'fraudlab', chapter: 'architecture'})}>Explore the model<Icon name="arrowRight" size={15}/></button>
          <button type="button" onClick={() => go({view: 'fraudlab', chapter: 'explorer'})}>Trace a prediction</button>
        </div>
      </div>
      <div className="fl-herodots">
        <DotMatrix total={BUDGET} columns={46} isFraud={r => fraud.has(r)} selected={picked} onSelect={setPicked}
          summary={`The ${BUDGET} highest-scored alerts. ${o.tp} were ground-truth fraud (filled) and ${o.fp} were not (hollow).`}/>
        <div className="fl-dotkey"><span><i className="tp"/>fraud ({o.tp})</span><span><i className="fp"/>not fraud ({o.fp})</span>
          <span className="quiet">Each dot is one alert, ranked 1 to {BUDGET}.</span></div>
        <div className="fl-dotinfo" aria-live="polite">
          {picked && row ? <>
            <Chip tone={row.fraud ? 'good' : 'warn'}>{row.fraud ? 'Ground truth: fraud · true positive' : 'Ground truth: not fraud · false positive'}</Chip>
            <span>Rank <b>{row.rank}</b> · model score <b>{row.score.toFixed(4)}</b> · amount {row.amount.toFixed(2)} · step {row.step}</span>
          </> : <span className="quiet">Select a dot to see its saved score and ground-truth label.</span>}
        </div>
      </div>
    </div>
    <h3 className="fl-sub">Three different systems. This page is only the middle one.</h3>
    <div className="fl-systems">
      <article><Chip>System A</Chip><h4>The product’s fraud rules</h4>
        <p className="fl-flow">Synthetic transactions → deterministic rules → alerts → human review → privacy → memory</p>
        <p className="quiet">This is what raises the alerts you see in Today and in every case.</p>
        <button type="button" disabled={!caseId} onClick={() => caseId && go({view: 'case', tx: caseId, from: 'today'})}>See how TrustLedger detects suspicious transactions<Icon name="arrowRight" size={14}/></button></article>
      <article className="here"><Chip tone="ai">System B · you are here</Chip><h4>BankSim ML research</h4>
        <p className="fl-flow">BankSim dataset → feature engineering → ML model → fraud predictions → evaluation → benchmark comparison</p>
        <p className="quiet">Offline and read-only. Nothing here runs inside the product, and no model produces the alerts in System A.</p></article>
      <article><Chip>System C</Chip><h4>BankSim data browsing</h4>
        <p className="fl-flow">Kenny’s export → FastAPI data-sources API → account selection → paginated transactions</p>
        <p className="quiet">A separate admin tool for looking at data. It is not what the model reads; the fraud labels used on this page come from the saved research artifacts, not from this tool.</p>
        {session.role === 'admin' ? <button type="button" onClick={() => go({view: 'sources'})}>Open Data sources<Icon name="arrowRight" size={14}/></button>
          : <small className="quiet">Admin only.</small>}</article>
    </div>
    <p className="quiet fl-foot">Research data: {TEST_FRAUD.toLocaleString()} fraud rows among {TEST_ROWS.toLocaleString()} test rows. Ranking order: score, then amount, then row index.</p>
  </section>;
}
