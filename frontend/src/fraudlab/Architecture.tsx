import {useState, type ReactNode} from 'react';
import {Chip} from '../ui';
import {ConfusionGrid} from './charts';
import {BUDGET, HEADLINE, evidence, model, outcomeAt, rows} from './data';
import {SRC, featureGroups} from './facts';

interface Layer {
  id: string; name: string; short: string; kind: 'Real' | 'Real + conceptual illustration';
  input: string; transform: string; output: string; why: string; effect: string; source: string; example: () => ReactNode;
}

const counts = evidence.splits.counts;
const m = model(HEADLINE);

/** Conceptual only: eighty rounds of small trees. It shows the idea of boosting, not the trained model's trees (those are not saved). */
function BoostingIdea() {
  const [n, setN] = useState(80);
  return <div className="fl-boost">
    <p><b>Conceptual illustration, not the trained model.</b> The real model adds 80 rounds. Each round is a small tree (up to 31 leaves) fitted to what the rounds before it still get wrong. Their outputs add up to one fraud score.</p>
    <div className="fl-trees" role="img" aria-label={`Rounds 1 to ${n} of 80 contribute to the score`}>
      {Array.from({length: 80}, (_, i) => <span key={i} className={i < n ? 'on' : ''}/>)}</div>
    <label htmlFor="fl-rounds">Rounds counted: <b>{n}</b> of 80</label>
    <input id="fl-rounds" type="range" min={1} max={80} value={n} onChange={e => setN(Number(e.target.value))}/>
    <p className="quiet">No tree structure, split value or per-round score is shown, because those were not saved with the research artifacts.</p>
  </div>;
}

const layers: Layer[] = [
  {id: 'population', name: 'Population check', short: 'Frozen slices', kind: 'Real',
    input: 'The BankSim file: a header plus 594,643 rows (kept outside git, CC BY-NC-SA 4.0).',
    transform: 'Orders rows by step (file order inside a step), counts rows and fraud per time slice, and compares them with the frozen contract. If any count differs, the run stops.',
    output: 'Four frozen slices: Train, Select, Confirm and Test.',
    why: 'The reported numbers only mean something on exactly these slices. A silent re-split would change them.',
    effect: 'Every later layer uses these slices and nothing else.', source: SRC.protocol + ' §2',
    example: () => <table className="fl-table"><thead><tr><th>Slice</th><th>Steps</th><th>Rows</th><th>Fraud</th></tr></thead><tbody>
      {(['train', 'selection', 'confirm', 'test'] as const).map(k => <tr key={k}><td>{k}</td><td>{evidence.splits[k][0]}–{evidence.splits[k][1]}</td><td>{counts[k].rows.toLocaleString()}</td><td>{counts[k].fraud.toLocaleString()}</td></tr>)}</tbody></table>},
  {id: 'raw', name: 'Raw record', short: 'Ten fields', kind: 'Real',
    input: 'One CSV row.', transform: 'Checked against the expected header (step, customer, age, gender, zipcodeOri, merchant, zipMerchant, category, amount, fraud). No field is added.',
    output: 'A typed record. Age, gender and zip codes are deliberately not used later.',
    why: 'Start from the dataset exactly as published. Remember that step is a simulated day, not a timestamp.',
    effect: 'Decides which fields can ever reach the model.', source: 'evaluation/research/benchmark/contract.py (header check)',
    example: () => { const r = rows[0]; return <dl className="fl-kv"><div><dt>step</dt><dd>{r.step}</dd></div><div><dt>amount</dt><dd>{r.amount.toFixed(2)}</dd></div>
      <div><dt>customer / merchant / category</dt><dd>codes {r.customer} / {r.merchant} / {r.category}</dd></div><div><dt>fraud (ground truth)</dt><dd>{r.fraud ? 'yes, kept out of the model' : 'no, kept out of the model'}</dd></div></dl>; }},
  {id: 'features', name: 'Feature construction', short: 'Seven groups', kind: 'Real',
    input: 'The typed record plus this customer’s earlier rows.', transform: 'Builds the feature groups listed below: amount, customer history, new-merchant and recency, 24-hour repeats, activity windows, BankSim category, and the merchant-aware arm.',
    output: 'One numeric feature vector per transaction.', why: 'Raw fields alone do not say whether a charge is unusual for this customer or this category.',
    effect: 'These vectors are the only thing the model sees.', source: SRC.v2 + ' (feature list)',
    example: () => <><ul className="fl-chips">{featureGroups.map(g => <li key={g.name}>{g.name}</li>)}</ul>
      <Chip tone="neutral">A real single-row feature vector: evidence pending (needs the model team’s export)</Chip></>},
  {id: 'temporal', name: 'Temporal and causal rules', short: 'Past only', kind: 'Real',
    input: 'Rows in step order.', transform: 'Customer history reads only earlier rows. Category and merchant statistics are estimated on steps 0–119 only. In training, a row’s merchant rate uses only earlier steps (the step-causal version).',
    output: 'Features that use neither the row’s future nor its own label.', why: 'A prediction must not benefit from outcomes that were unknown at that moment.',
    effect: 'Keeps test scores an honest stand-in for “unseen future”, within this dataset’s limits.', source: SRC.leakage,
    example: () => <ul className="plain"><li>Test features differ from the frozen steps 0–119 rate by at most 0.0.</li><li>No Select, Confirm or Test label enters a feature.</li>
      <li>Limit: no test merchant is unseen in training, so new-merchant generalization is untested.</li></ul>},
  {id: 'prep', name: 'Preprocessing and variants', short: 'Compared on Select', kind: 'Real',
    input: 'Feature vectors.', transform: 'Adds a category amount CDF and a multiple of the category median (from training steps only), uses BankSim’s original category, and compares many model variants on the Select slice.',
    output: 'The model-ready matrix and a Select-slice ranking of variants.', why: 'Model choice was made on the Select slice only, so the Test slice did not pick the winner.',
    effect: 'Chooses which variant is carried forward.', source: SRC.framework + ' (validation_ranking)',
    example: () => <table className="fl-table"><thead><tr><th>Variant</th><th>Select-slice AP</th></tr></thead><tbody>
      {[...evidence.validation_ranking].sort((a, b) => b.val_ap - a.val_ap).slice(0, 8).map(v => <tr key={v.name}><td>{v.name}</td><td>{v.val_ap.toFixed(4)}</td></tr>)}</tbody></table>},
  {id: 'model', name: 'The model', short: 'Gradient boosting', kind: 'Real + conceptual illustration',
    input: 'The model-ready matrix, training rows only (steps 0–119).', transform: 'A scikit-learn HistGradientBoostingClassifier: trees are added one after another, each fitted to the errors of the rounds before it, and their outputs add up to a fraud score.',
    output: 'A fraud score for every transaction.', why: 'Gradient-boosted trees are a common fit for tabular data like this: they capture thresholds and interactions without heavy scaling. (General rationale, not a measured claim.)',
    effect: 'Only the ordering of the scores matters downstream.', source: SRC.framework + ' (hgb_hyperparameters)',
    example: () => <><table className="fl-table"><thead><tr><th>Hyperparameter</th><th>Value</th></tr></thead><tbody>
      {Object.entries(evidence.hgb_hyperparameters).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td>{String(v)}</td></tr>)}
      <tr><td className="mono">merchant_shrinkage_alpha</td><td>{evidence.merchant_shrinkage_alpha}</td></tr></tbody></table>
      <p className="quiet">The Select slice picked <span className="mono">{evidence.selected_model_on_selection_slice}</span>. The headline model, <span className="mono">{HEADLINE}</span>, is that model retrained with step-causal merchant rates after the leakage audit. The same settings are used for every boosting variant; there was no wide search.</p>
      <BoostingIdea/></>},
  {id: 'ranking', name: 'Scores and ranking', short: 'Order matters', kind: 'Real',
    input: 'One score per transaction.', transform: 'Sort by score, highest first. Ties go to the larger amount, then the lower row index.',
    output: 'A ranked list of all 111,306 test transactions.', why: 'A fixed, repeatable order makes “top k” well defined, including for models whose scores tie.',
    effect: 'Decides who is inside the review queue.', source: SRC.protocol + ' §3',
    example: () => <><p className="quiet">The headline model produces {m.score_unique_values.toLocaleString()} distinct scores. Top of the saved ranking:</p>
      <table className="fl-table"><thead><tr><th>Rank</th><th>Score</th><th>Ground truth</th></tr></thead><tbody>{rows.slice(0, 5).map(r => <tr key={r.rank}><td>{r.rank}</td><td>{r.score.toFixed(4)}</td><td>{r.fraud ? 'fraud' : 'not fraud'}</td></tr>)}</tbody></table></>},
  {id: 'budget', name: 'Alert budget', short: 'Top 919', kind: 'Real',
    input: 'The ranked list.', transform: 'Keep the top 919. That is the number of alerts the reproduced current rules raise on the same slice, so review workload is held constant. (An F1 threshold also exists, chosen on the Select slice only.)',
    output: 'Alerted versus not alerted.', why: 'Investigators have limited capacity; the queue size is a business constraint, not a model setting.',
    effect: 'Fixes how many reviews are spent, so catching more fraud means fewer false alarms.', source: SRC.protocol + ' §3',
    example: () => <ConfusionGrid o={outcomeAt(m, BUDGET)}/>},
  {id: 'eval', name: 'Evaluation', short: 'Held-out test', kind: 'Real',
    input: 'The ranking plus the test slice’s ground-truth labels.', transform: 'Computes average precision, ROC-AUC, and TP, FP, FN, TN at 919, then a paired bootstrap against the best public pipeline.',
    output: 'The metrics shown in Chapter 4 and the benchmark arena.', why: 'Ground truth is used here and only here, to score, never to predict.',
    effect: 'Feeds the benchmark comparison.', source: SRC.leaderboard,
    example: () => { const a = evidence.bootstrap.headline_vs_public_lgbm_customer_blocks.ap_difference, b = evidence.bootstrap.headline_vs_public_lgbm_step_blocks.ap_difference;
      return <ul className="plain"><li>Average precision <b>{m.average_precision.toFixed(6)}</b>, ROC-AUC <b>{m.roc_auc.toFixed(6)}</b>.</li>
        <li>Versus the best public pipeline (AP difference): customer-block 95% interval {a.ci95_low.toFixed(4)} to {a.ci95_high.toFixed(4)} ({a.includes_zero ? 'includes' : 'excludes'} zero); step-block {b.ci95_low.toFixed(4)} to {b.ci95_high.toFixed(4)} ({b.includes_zero ? 'includes' : 'excludes'} zero).</li>
        <li>The two block methods disagree, so this is a close result, not a clear win.</li></ul>; }},
];

/** Chapter 3: the model pipeline as an inspectable stack. Click a layer to see its real inputs, computation and effect on what follows. */
export default function Architecture() {
  const [sel, setSel] = useState('features');
  const at = layers.findIndex(l => l.id === sel);
  const layer = layers[at];
  return <section aria-labelledby="fl-title" className="fl-chapter fl-arch">
    <h2 id="fl-title" className="visually-hidden">Model architecture</h2>
    <p className="fl-lede">Nine layers, taken from the research code. Select one to see what goes in, what happens, what comes out, and what it changes downstream.</p>
    <div className="fl-archgrid">
      <ol className="fl-stack" aria-label="Pipeline layers">
        {layers.map((l, i) => <li key={l.id} className={(i === at ? 'sel ' : '') + (i > at ? 'down' : i < at ? 'up' : '')}>
          <button type="button" aria-current={i === at ? 'true' : undefined} onClick={() => setSel(l.id)}>
            <span className="node">{i + 1}</span><span className="lname"><b>{l.name}</b><small>{l.short}</small></span>
            {l.kind !== 'Real' && <Chip tone="ai">+ conceptual</Chip>}</button></li>)}
      </ol>
      <article className="fl-detail" aria-live="polite" key={layer.id}>
        <header><span className="node big">{at + 1}</span><h3>{layer.name}</h3><Chip tone={layer.kind === 'Real' ? 'good' : 'ai'}>{layer.kind}</Chip></header>
        <dl className="fl-five">
          <div><dt>Input</dt><dd>{layer.input}</dd></div><div><dt>What happens</dt><dd>{layer.transform}</dd></div><div><dt>Output</dt><dd>{layer.output}</dd></div>
          <div><dt>Why it exists</dt><dd>{layer.why}</dd></div><div><dt>Effect on the next stage</dt><dd>{layer.effect}</dd></div></dl>
        <div className="fl-example"><h4>From the real artifacts</h4>{layer.example()}</div>
        <p className="quiet">Source: <span className="mono">{layer.source}</span></p>
      </article>
    </div>
  </section>;
}
