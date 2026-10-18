import {useState} from 'react';
import {Chip} from '../ui';
import {Bars} from './charts';
import {evidence, model, rowAtRank} from './data';
import {SRC, featureGroups, leakFacts, ownLabelGap} from './facts';

const schema: {field: string; usage: string; note: string}[] = [
  {field: 'step', usage: 'Used for order and windows', note: 'A simulated day index (0–179), not a real timestamp. There is no hour or minute in this dataset.'},
  {field: 'customer', usage: 'Only to find that customer’s earlier rows', note: 'The identifier itself is not fed to the model.'},
  {field: 'age, gender', usage: 'Not used', note: 'Deliberately left out.'},
  {field: 'zipcodeOri, zipMerchant', usage: 'Not used', note: 'Deliberately left out.'},
  {field: 'merchant', usage: 'Used indirectly', note: 'To tell whether this customer has used the merchant before; the merchant-aware arm also uses its training-period fraud rate. The identifier itself is not fed to the model.'},
  {field: 'category', usage: 'Used', note: 'BankSim’s original category, not the product’s coarse categories.'},
  {field: 'amount', usage: 'Used', note: 'On a log scale, and relative to history.'},
  {field: 'fraud', usage: 'Ground-truth label, never an input', note: 'Used to train on steps 0–119 and to score results afterwards. Not available when a prediction is made.'},
];

const slices = [
  {key: 'train', label: 'Train', range: [0, 119]}, {key: 'selection', label: 'Select', range: [120, 134]},
  {key: 'confirm', label: 'Confirm', range: [135, 149]}, {key: 'test', label: 'Test', range: [150, 179]},
] as const;

/** Chapter 2: from a raw BankSim record to model inputs, and the line the pipeline must never cross. */
export default function Features() {
  const [t, setT] = useState(160);
  const [open, setOpen] = useState<string | null>(featureGroups[0].name);
  const slice = slices.find(s => t >= s.range[0] && t <= s.range[1])!;
  const sample = rowAtRank(1)!;
  const variants = ['v2_merchant', 'v2_merchant_step_causal', 'v2_merchant_expanding'].map(n => model(n));
  const variantLabel: Record<string, string> = {v2_merchant: 'Original (counts a row’s own label)', v2_merchant_step_causal: 'Step-causal (headline)', v2_merchant_expanding: 'Expanding window'};
  return <section aria-labelledby="fl-title" className="fl-chapter">
    <h2 id="fl-title" className="visually-hidden">Data and feature engineering</h2>
    <p className="fl-lede">Raw record → validation → features → temporal rules → model input. Every feature must be computable from what was known at that moment.</p>
    <div className="fl-cols">
      <div className="fl-card">
        <h3>The raw BankSim record</h3>
        <table className="fl-table"><thead><tr><th>Field</th><th>Role in the model</th><th>Notes</th></tr></thead>
          <tbody>{schema.map(s => <tr key={s.field}><td className="mono">{s.field}</td><td>{s.usage}</td><td className="quiet">{s.note}</td></tr>)}</tbody></table>
        <p className="quiet">A real saved test row has: step {sample.step}, amount {sample.amount.toFixed(2)}, customer code {sample.customer}, merchant code {sample.merchant}, category code {sample.category}. The saved artifact keeps integer codes, not names, and not the engineered feature values.</p>
        <Chip tone="neutral">Engineered feature values for single rows: evidence pending (needs the model team’s export)</Chip>
      </div>
      <div className="fl-card">
        <h3>Feature groups (click to expand)</h3>
        <ul className="fl-acc">{featureGroups.map(g => <li key={g.name}>
          <button type="button" aria-expanded={open === g.name} onClick={() => setOpen(open === g.name ? null : g.name)}>{g.name}</button>
          {open === g.name && <dl>
            <div><dt>What it is</dt><dd>{g.what}</dd></div><div><dt>How it is calculated</dt><dd>{g.how}</dd></div>
            <div><dt>Why it may help</dt><dd>{g.why}</dd></div><div><dt>Known at prediction time?</dt><dd>{g.atT}</dd></div>
            <div><dt>Leakage risk</dt><dd>{g.leakage}</dd></div></dl>}</li>)}</ul>
        <p className="quiet">Source: <span className="mono">{SRC.v2}</span>. Exact formulas: <span className="mono">evaluation/research/v2/run_framework.py</span>.</p>
      </div>
    </div>
    <div className="fl-card">
      <h3>The causal boundary: choose a step T</h3>
      <div className="fl-slider"><label htmlFor="fl-t">Predicting a transaction at step <b>T = {t}</b> ({slice.label} slice)</label>
        <input id="fl-t" type="range" min={0} max={179} value={t} onChange={e => setT(Number(e.target.value))}/></div>
      <div className="fl-timeline" role="img" aria-label={`Steps 0 to 179. Step ${t} is in the ${slice.label} slice. Steps after ${t} are the future and unavailable.`}>
        {slices.map(s => <div key={s.key} className={'sl ' + s.key + (s.key === slice.key ? ' on' : '')} style={{flex: s.range[1] - s.range[0] + 1}}>
          <b>{s.label}</b><small>{s.range[0]}–{s.range[1]} · {evidence.splits.counts[s.key].rows.toLocaleString()} rows</small></div>)}
        <span className="now" style={{left: `${(t / 180) * 100}%`}}/>
        <span className="future" style={{left: `${((t + 1) / 180) * 100}%`, right: 0}}/>
      </div>
      <div className="fl-cols">
        <div><h4>Available at T</h4><ul className="plain">
          <li>This customer’s earlier rows (not later ones).</li>
          <li>Category and merchant statistics <b>frozen from steps 0–119</b>, never re-estimated with later data.</li>
          <li>The transaction’s own fields (amount, category, step).</li></ul></div>
        <div><h4>Not available at T</h4><ul className="plain">
          <li>Any transaction after this one (the shaded future).</li>
          <li>Any ground-truth label from the Select, Confirm or Test slices when building features.</li>
          {t < 120 && <li><b>In training: this row’s own label, and labels from later steps,</b> must not be counted in its merchant fraud rate. That was the leak found in the original version.</li>}
          {t >= 150 && <li>Test labels are used only to score results afterwards, never to make features.</li>}</ul></div>
      </div>
    </div>
    <div className="fl-card">
      <h3>Leakage, found and corrected by our own audit</h3>
      <p>The original merchant fraud rate leaked into <b>training</b> features: each training row’s rate included its own label, and for {leakFacts.laterRows} of the training rows it also included labels from later steps.
        The step-causal version builds training features from earlier steps only. <b>Test features were never affected</b>: they use the frozen steps 0–119 rate, with no Select, Confirm or Test labels.</p>
      <Bars label="Average precision of three merchant-rate variants" max={1} format={v => v.toFixed(6)} items={variants.map(v => ({
        key: v.model, label: variantLabel[v.model], value: v.average_precision, tone: v.model === 'v2_merchant_step_causal' ? 'good' : 'muted'}))}/>
      <p className="quiet">Own-label effect in the original rate (absolute difference): about {Number(ownLabelGap.trainMean).toExponential(1)} on average over training rows,
        {' '}{Number(ownLabelGap.fraudRows).toExponential(1)} on training fraud rows, up to {Number(ownLabelGap.max).toFixed(4)}. Source: <span className="mono">{SRC.leakage}</span>.
        The step-causal version moves AP by −0.0009 (the research notes did not bootstrap this difference).</p>
      <p className="quiet">This is evidence of care, not proof of zero leakage: the research team’s own audit still lists missing leakage-status flags for several of our models.
        Also, no test merchant is unseen in training, so this split cannot show that the model generalizes to new merchants.</p>
    </div>
  </section>;
}
