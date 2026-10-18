import {useState} from 'react';
import {Callout, Chip, Seg} from '../ui';
import {Bars, PRChart, type Bar} from './charts';
import {BUDGET, HEADLINE, TEST_FRAUD, TEST_ROWS, evidence, model, models, provenance, type ModelResult} from './data';
import {SRC, publicSources, references} from './facts';

type Metric = 'average_precision' | 'precision' | 'recall' | 'FP' | 'roc_auc';
type Group = 'matched' | 'full' | 'all';

const names: Record<string, string> = {
  v2_merchant: 'TrustLedger merchant-aware (original)', v2_merchant_step_causal: 'TrustLedger merchant-aware, step-causal (headline)',
  v2_merchant_expanding: 'TrustLedger merchant-aware, expanding window', v2_enriched_sqrt: 'TrustLedger, no merchant fraud rate',
  pr14_mapped_hgb: 'Earlier TrustLedger HGB (PR #14)', prod_rules: 'Current product rules (reproduced)',
  trackA_atavci_xgb_logistic: 'atavci XGBoost, logistic', trackB_atavci_xgb_logistic: 'atavci XGBoost, logistic',
  trackA_atavci_xgb_hinge: 'atavci XGBoost, hinge (0/1 output)', trackB_atavci_xgb_hinge: 'atavci XGBoost, hinge (0/1 output)',
  trackA_atavci_rf: 'atavci Random Forest', trackB_atavci_rf: 'atavci Random Forest',
  trackA_atavci_soft_vote_approx: 'atavci soft vote (approximation)', trackB_atavci_soft_vote_approx: 'atavci soft vote (approximation)',
  trackA_sushmitha_lgbm: '0xSushmitha LightGBM', trackB_sushmitha_lgbm: '0xSushmitha LightGBM',
};
const display = (m: ModelResult) => (names[m.model] ?? m.model) + (m.track ? ` · Track ${m.track}` : '');
const metricInfo: Record<Metric, {label: string; fmt: (v: number) => string; lower?: boolean; text: string}> = {
  average_precision: {label: 'Average precision', fmt: v => v.toFixed(4), text: 'Quality of the whole ranking. Higher is better.'},
  precision: {label: 'Precision at 919', fmt: v => (v * 100).toFixed(1) + '%', text: 'Share of the top 919 that is fraud. Higher is better.'},
  recall: {label: 'Recall at 919', fmt: v => (v * 100).toFixed(1) + '%', text: `Share of the ${TEST_FRAUD.toLocaleString()} test fraud inside the top 919. Higher is better.`},
  FP: {label: 'False positives at 919', fmt: v => String(v), lower: true, text: 'Legitimate transactions in the top 919. Lower is better.'},
  roc_auc: {label: 'ROC-AUC', fmt: v => v.toFixed(4), text: 'Near 1.0 for almost any model on rare-event data, so it separates models poorly here.'},
};
const fidelityBadge = (f: string) => f === 'TRUSTLEDGER_REPRODUCTION' ? 'ours' : f === 'LEAKAGE_VARIANT' ? 'ours · leakage-audit variant' : f.toLowerCase();
const tone = (m: ModelResult) => m.model === HEADLINE ? 'good' : m.model.startsWith('v2_') || m.model.startsWith('pr14') || m.model === 'prod_rules' ? 'tl' : 'pub';
const inGroup = (m: ModelResult, g: Group) => g === 'all' || (g === 'matched'
  ? m.model === 'v2_enriched_sqrt' || m.track === 'A'
  : m.model.startsWith('v2_merchant') || m.track === 'B');

/** Chapter 6: the benchmark arena. Only results measured under one frozen protocol are plotted together. */
export default function Arena() {
  const [metric, setMetric] = useState<Metric>('average_precision');
  const [group, setGroup] = useState<Group>('full');
  const [sel, setSel] = useState<string>(HEADLINE);
  const info = metricInfo[metric];
  const shown = models.filter(m => inGroup(m, group)).sort((a, b) => info.lower ? (a[metric] as number) - (b[metric] as number) : (b[metric] as number) - (a[metric] as number));
  const max = metric === 'FP' ? Math.max(...shown.map(m => m.FP), 1) : 1;
  const bars: Bar[] = shown.map(m => ({key: m.model, label: display(m), value: m[metric] as number, tone: tone(m), badge: fidelityBadge(m.fidelity)}));
  const d = model(sel), head = model(HEADLINE), pub = model('trackB_sushmitha_lgbm');
  const cust = evidence.bootstrap.headline_vs_public_lgbm_customer_blocks.ap_difference, step = evidence.bootstrap.headline_vs_public_lgbm_step_blocks.ap_difference;
  const mt = evidence.merchant_concentration as Record<string, {tp: number; tp_in_top5_test_fraud_merchants: number}>;
  const rules = model('prod_rules'), enriched = model('v2_enriched_sqrt'), atavci = model('trackA_atavci_xgb_logistic');
  return <section aria-labelledby="fl-title" className="fl-chapter fl-arena">
    <h2 id="fl-title" className="visually-hidden">Benchmark comparison</h2>
    <p className="fl-lede">Every model below was scored on the same {TEST_ROWS.toLocaleString()} test rows, with the same split and the same {BUDGET}-alert budget. Public pipelines were re-run by us on our split, so they are <b>adapted</b>, not reproduced verbatim.</p>
    <Callout tone="neutral" icon="info" title="The honest summary">
      The headline model’s average precision is {head.average_precision.toFixed(4)} against {pub.average_precision.toFixed(4)} for the best public pipeline (a difference of {(head.average_precision - pub.average_precision).toFixed(4)}). That is inside the 0.01 “close” band set in advance, and the two bootstrap methods disagree
      (customer blocks: {cust.ci95_low.toFixed(4)} to {cust.ci95_high.toFixed(4)}, {cust.includes_zero ? 'includes' : 'excludes'} zero; step blocks: {step.ci95_low.toFixed(4)} to {step.ci95_high.toFixed(4)}, {step.includes_zero ? 'includes' : 'excludes'} zero). So we call it <b>a tie</b>, not a win.
      At 919 alerts the public pipeline finds {pub.TP} fraud with {pub.FP} false alarms; ours finds {head.TP} with {head.FP}.</Callout>
    <div className="fl-controls">
      <Seg label="Metric" value={metric} onChange={setMetric} options={(Object.keys(metricInfo) as Metric[]).map(k => ({key: k, label: metricInfo[k].label}))}/>
      <Seg label="Which models" value={group} onChange={setGroup} options={[
        {key: 'full', label: 'Full pipelines'}, {key: 'matched', label: 'Matched features'}, {key: 'all', label: 'Everything measured'}]}/>
    </div>
    <p className="quiet">{info.text} {group === 'matched' ? 'Matched features: no merchant fraud rate and no customer or merchant identity codes for anyone, so the learner is what differs.'
      : group === 'full' ? 'Full pipelines: each uses its own features, including merchant identity or merchant fraud rate.' : 'Includes the current rules and earlier baselines.'}</p>
    <div className="fl-cols fl-arenacols">
      <div className="fl-card"><Bars items={bars} max={max} format={info.fmt} selected={sel} onSelect={setSel} label={`${info.label} by model`}/></div>
      <div className="fl-card fl-modeldetail"><h3>{display(d)}</h3>
        <Chip tone={d.fidelity === 'TRUSTLEDGER_REPRODUCTION' || d.fidelity === 'LEAKAGE_VARIANT' ? 'good' : 'ai'}>{fidelityBadge(d.fidelity)}</Chip>
        {d.fidelity === 'LEAKAGE_VARIANT' && <p className="quiet">A TrustLedger version rebuilt to test or remove the merchant-rate leak. “Adapted” means a public pipeline re-run on our split, with documented changes.</p>}
        <dl className="fl-kv"><div><dt>Average precision</dt><dd>{d.average_precision.toFixed(6)}</dd></div><div><dt>ROC-AUC</dt><dd>{d.roc_auc.toFixed(6)}</dd></div>
          <div><dt>At 919 alerts</dt><dd>{d.TP} true / {d.FP} false positives</dd></div><div><dt>Precision · recall</dt><dd>{(d.precision * 100).toFixed(1)}% · {(d.recall * 100).toFixed(1)}%</dd></div>
          <div><dt>Distinct scores</dt><dd>{d.score_unique_values.toLocaleString()}{d.score_unique_values <= 2 ? ' (0/1 output, so no real ranking)' : ''}</dd></div></dl>
        {d.architecture && <p className="quiet">{d.architecture}</p>}
        {d.leakage_status && <p className="quiet">Leakage note: {d.leakage_status}</p>}
        {d.source_url && <p><a href={d.source_url} target="_blank" rel="noreferrer">Source ↗</a></p>}</div>
    </div>
    <div className="fl-card"><h3>Precision-recall overlay</h3>
      <PRChart k={BUDGET} series={[{name: names[HEADLINE], model: head, tone: 'c1'}, {name: names.trackB_sushmitha_lgbm + ' · Track B', model: pub, tone: 'c2'}, {name: names.v2_enriched_sqrt, model: enriched, tone: 'c3'},
        {name: names.trackA_atavci_xgb_logistic + ' · Track A', model: atavci, tone: 'c4'}]}
        caption="Exact curves from each model’s saved scores. Models with only 0/1 output have no curve and are omitted."/></div>
    <div className="fl-cols">
      <div className="fl-card"><h3>What is verified in our favor</h3>
        <ul className="fl-proof">
          <li><b>High average precision.</b> {head.average_precision.toFixed(4)}, against {rules.average_precision.toFixed(3)} for the current product rules on the same slice.</li>
          <li><b>Precision under a fixed budget.</b> {head.TP} of {BUDGET} alerts ({(head.precision * 100).toFixed(1)}%), versus {rules.TP} for the rules.</li>
          <li><b>False-alarm control.</b> {head.FP} false alarms against {rules.FP} for the rules at the same workload.</li>
          <li><b>Time-aware features, leakage-aware audit.</b> History looks only backward, and our own audit found and corrected a training-feature leak (Chapter 2).</li>
          <li><b>Reproducible.</b> Saved scores, labels and hashes are in the repository, and this page recomputes every confusion count from them.</li></ul></div>
      <div className="fl-card"><h3>Limits you should know</h3>
        <ul className="fl-proof warn">
          <li>The test slice had been inspected before; it is not a blind holdout.</li>
          <li>BankSim is synthetic and non-commercial licensed; results do not transfer to real banks.</li>
          <li>The big gain comes from merchant information ({enriched.average_precision.toFixed(3)} without it, {head.average_precision.toFixed(3)} with it). {mt[HEADLINE].tp_in_top5_test_fraud_merchants} of our {mt[HEADLINE].tp} true positives sit in just five merchants, and no test merchant is unseen in training. It memorizes this simulator’s merchants and the research team does not recommend using it in the product.</li>
          <li>With the {BUDGET}-alert budget, {head.FN} of {TEST_FRAUD.toLocaleString()} fraud cases are still missed (recall {(head.recall * 100).toFixed(1)}%).</li>
          <li>On matched features without merchant information we tie the public XGBoost ({enriched.average_precision.toFixed(4)} vs {atavci.average_precision.toFixed(4)}).</li>
          <li>The research model is offline. It does not produce the product’s alerts.</li></ul></div>
    </div>
    <div className="fl-card"><h3>Published reference results (not directly comparable)</h3>
      <p className="quiet">These use different splits, rows or metrics. They are shown for context and are never plotted against ours.</p>
      <table className="fl-table"><thead><tr><th>Source</th><th>Published</th><th>Why it is not comparable</th><th>Value on our protocol</th></tr></thead><tbody>
        {references.map(r => <tr key={r.who}><td>{r.who}</td><td>{r.what}</td><td className="quiet">{r.why}</td><td>N/A</td></tr>)}</tbody></table>
      <p className="quiet">Other public BankSim notebooks were checked and excluded: no runnable code, a different dataset, a pre-split fit that leaks, or contradictory published numbers (see <span className="mono">{SRC.shortlist}</span>).
        We make no claim about any Kaggle ranking.</p>
      <ul className="plain">{publicSources.map(s => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.name} ↗</a></li>)}</ul></div>
    <p className="quiet fl-foot">Data hash record: <span className="mono">frontend/src/fraudlab/data/provenance.json</span> (leaderboard last changed in commit <span className="mono">{provenance.leaderboard_last_changed_in_commit.slice(0, 7)}</span>).</p>
  </section>;
}
