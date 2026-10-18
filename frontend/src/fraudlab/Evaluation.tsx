import {useState} from 'react';
import {Bars, ConfusionGrid, PRChart, type Series} from './charts';
import {BUDGET, HEADLINE, TEST_FRAUD, TEST_ROWS, evidence, model, outcomeAt} from './data';

const pickable = [
  {name: 'Headline: merchant-aware, step-causal HGB', model: HEADLINE, tone: 'c1'},
  {name: 'Public LightGBM pipeline (Track B, adapted)', model: 'trackB_sushmitha_lgbm', tone: 'c2'},
  {name: 'TrustLedger without merchant fraud rate', model: 'v2_enriched_sqrt', tone: 'c3'},
  {name: 'Earlier HGB (PR #14)', model: 'pr14_mapped_hgb', tone: 'c4'},
];
const slices = [
  {key: 'train', label: 'Train', role: 'Fit the model', rows: evidence.splits.counts.train, steps: evidence.splits.train},
  {key: 'selection', label: 'Select', role: 'Choose the model', rows: evidence.splits.counts.selection, steps: evidence.splits.selection},
  {key: 'confirm', label: 'Confirm', role: 'Check a pre-written merchant-rate rule (cannot change the winner)', rows: evidence.splits.counts.confirm, steps: evidence.splits.confirm},
  {key: 'test', label: 'Test', role: 'Report results', rows: evidence.splits.counts.test, steps: evidence.splits.test},
];

/** Chapter 4: how the model was trained and judged, with curves computed exactly from the saved scores and labels. */
export default function Evaluation() {
  const [on, setOn] = useState<string[]>([HEADLINE, 'trackB_sushmitha_lgbm']);
  const [k, setK] = useState(BUDGET);
  const series: Series[] = pickable.filter(p => on.includes(p.model)).map(p => ({name: p.name, model: model(p.model), tone: p.tone}));
  const head = model(HEADLINE), o = outcomeAt(head, k);
  const total = TEST_ROWS + slices.slice(0, 3).reduce((n, s) => n + s.rows.rows, 0);
  const sel = [...evidence.validation_ranking].sort((a, b) => b.val_ap - a.val_ap);
  const toggle = (name: string) => setOn(cur => cur.includes(name) ? cur.filter(n => n !== name) : [...cur, name]);
  return <section aria-labelledby="fl-title" className="fl-chapter">
    <h2 id="fl-title" className="visually-hidden">Training and evaluation</h2>
    <p className="fl-lede">Trained on the past, chosen on a later slice, reported on the latest slice.</p>
    <div className="fl-card">
      <h3>The time-based split</h3>
      <div className="fl-splitbar" role="img" aria-label="Four time slices: train, select, confirm and test">
        {slices.map(s => <div key={s.key} className={'sl ' + s.key} style={{flex: s.rows.rows}}><b>{s.label}</b><small>steps {s.steps[0]}–{s.steps[1]}</small></div>)}
      </div>
      <table className="fl-table"><thead><tr><th>Slice</th><th>Rows</th><th>Fraud</th><th>Role</th></tr></thead><tbody>
        {slices.map(s => <tr key={s.key}><td>{s.label}</td><td>{s.rows.rows.toLocaleString()}</td><td>{s.rows.fraud.toLocaleString()}</td><td>{s.role}</td></tr>)}
        <tr><td><b>Total</b></td><td>{total.toLocaleString()}</td><td>{evidence.dataset.fraud.toLocaleString()}</td><td/></tr></tbody></table>
      <p className="quiet"><b>How credible is this?</b> A later slice is a fairer test than a random one, but steps 150–179 were already inspected by earlier experiments, so this is a reproducible comparison, <b>not</b> a blind holdout. Hyperparameters were fixed before this test and not tuned on it.</p>
    </div>
    <div className="fl-card">
      <h3>Model selection used the Select slice only</h3>
      <Bars label="Select-slice average precision of the model variants" max={1} format={v => v.toFixed(4)}
        items={sel.slice(0, 8).map(v => ({key: v.name, label: v.name, value: v.val_ap, tone: v.name === evidence.selected_model_on_selection_slice ? 'good' : 'muted',
          badge: v.name === evidence.selected_model_on_selection_slice ? 'selected' : undefined}))}/>
      <p className="quiet">Top 8 of {sel.length} variants. Tie-breaks were written down in advance: prefer no merchant rate, then fewer feature groups.</p>
    </div>
    <div className="fl-card">
      <h3>Precision-recall curves (exact, from saved scores and labels)</h3>
      <fieldset className="fl-pick"><legend>Models to draw</legend>
        {pickable.map(p => <label key={p.model}><input type="checkbox" checked={on.includes(p.model)} onChange={() => toggle(p.model)}/><i className={'sw ' + p.tone}/>{p.name}</label>)}</fieldset>
      <div className="fl-slider"><label htmlFor="fl-k2">Mark the alert budget: <b>{k.toLocaleString()}</b> alerts</label>
        <input id="fl-k2" type="range" min={100} max={3000} value={k} onChange={e => setK(Number(e.target.value))}/></div>
      <PRChart series={series} k={k} caption={<>Each vertex is one of the {TEST_FRAUD.toLocaleString()} test fraud cases, placed where the model ranked it. The dots mark the chosen budget.
        Curves follow the benchmark’s ranking order; the published average precision values are the ones from the leaderboard.</>}/>
    </div>
    <div className="fl-cols">
      <div className="fl-card"><h3>Outcomes at {k.toLocaleString()} alerts (headline model)</h3><ConfusionGrid o={o}/>
        <p className="quiet">Precision {(o.precision * 100).toFixed(2)}% · recall {(o.recall * 100).toFixed(2)}% (of the {TEST_FRAUD.toLocaleString()} test fraud, not the whole file’s {evidence.dataset.fraud.toLocaleString()}).</p></div>
      <div className="fl-card"><h3>What each metric means</h3>
        <dl className="fl-metrics">
          <div><dt>Average precision (AP)</dt><dd>Quality of the whole ranking: how high fraud sits above legitimate. Headline: <b>{head.average_precision.toFixed(6)}</b>.</dd></div>
          <div><dt>ROC-AUC</dt><dd>Chance a random fraud outranks a random legitimate transaction: <b>{head.roc_auc.toFixed(6)}</b>. It looks near-perfect on any rare-event data, so AP and precision at a budget are the stricter views.</dd></div>
          <div><dt>Precision at k</dt><dd>Share of the top k that is fraud. Operational: how much review effort is well spent.</dd></div>
          <div><dt>Recall at k</dt><dd>Share of all fraud inside the top k. A budget of {BUDGET} cannot reach 100%: {head.FN} fraud cases fall below it.</dd></div>
          <div><dt>Accuracy</dt><dd>Not used to choose models: it stays above 98% even for a model that finds nothing.</dd></div></dl></div>
    </div>
  </section>;
}
