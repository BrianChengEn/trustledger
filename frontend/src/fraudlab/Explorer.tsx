import {useState} from 'react';
import {Chip} from '../ui';
import {ConfusionGrid} from './charts';
import {BUDGET, HEADLINE, TEST_FRAUD, TEST_ROWS, model, outcomeAt, outcomeOfRow, rows, type Outcome4, type RankedRow} from './data';

type Filter = 'top' | 'fp' | 'fn';
const PAGE = 12, SAVED_TOP = 1200;
const badge: Record<Outcome4, {tone: 'good' | 'warn' | 'danger' | 'neutral'; text: string}> = {
  TP: {tone: 'good', text: 'True positive'}, FP: {tone: 'warn', text: 'False positive'}, FN: {tone: 'danger', text: 'False negative'}, TN: {tone: 'neutral', text: 'True negative'},
};

function why(row: RankedRow, k: number, outcome: Outcome4) {
  const side = row.rank <= k ? `ranked ${row.rank.toLocaleString()}, inside the top ${k.toLocaleString()}, so it is an alert` : `ranked ${row.rank.toLocaleString()}, outside the top ${k.toLocaleString()}, so it is not an alert`;
  const truth = row.fraud ? 'the ground-truth label says fraud' : 'the ground-truth label says not fraud';
  return `${side}; ${truth}. That makes it a ${badge[outcome].text.toLowerCase()}.`;
}

/** Chapter 5: real saved predictions. Ground truth, model score and evaluation outcome are three different things, shown separately. */
export default function Explorer() {
  const m = model(HEADLINE);
  const [k, setK] = useState(BUDGET);
  const [filter, setFilter] = useState<Filter>('top');
  const [page, setPage] = useState(0);
  const [pick, setPick] = useState<number | null>(null);
  const o = outcomeAt(m, k);
  const list = rows.filter(r => filter === 'top' ? r.rank <= SAVED_TOP : filter === 'fp' ? r.rank <= k && !r.fraud : r.fraud && r.rank > k);
  const pages = Math.max(1, Math.ceil(list.length / PAGE));
  const cur = Math.min(page, pages - 1), shown = list.slice(cur * PAGE, cur * PAGE + PAGE);
  const row = rows.find(r => r.rank === pick);
  const setF = (f: Filter) => { setFilter(f); setPage(0); };
  return <section aria-labelledby="fl-title" className="fl-chapter fl-explorer">
    <h2 id="fl-title" className="visually-hidden">Prediction explorer</h2>
    <p className="fl-lede">Real saved predictions for the {TEST_ROWS.toLocaleString()} held-out test rows. No score here is made up and nothing runs in your browser.</p>
    <div className="fl-legend" aria-label="Three different things">
      <div><Chip tone="good">Ground truth</Chip><small>The dataset’s original fraud label. Never an input to the model.</small></div>
      <div><Chip tone="ai">Model score</Chip><small>The headline model’s saved score for the row.</small></div>
      <div><Chip>Evaluation outcome</Chip><small>TP, FP, FN or TN, from the score’s rank against the chosen budget and the ground truth.</small></div>
    </div>
    <div className="fl-card">
      <h3>Alert budget</h3>
      <div className="fl-slider"><label htmlFor="fl-k3">Review the top <b>{k.toLocaleString()}</b> alerts</label>
        <input id="fl-k3" type="range" min={1} max={5000} value={k} onChange={e => { setK(Number(e.target.value)); setPage(0); }}/>
        <div className="fl-presets">{[100, 500, BUDGET, 2000].map(n => <button key={n} type="button" aria-pressed={k === n} onClick={() => { setK(n); setPage(0); }}>{n}</button>)}</div></div>
      <div className="fl-cols">
        <ConfusionGrid o={o}/>
        <div><p className="fl-big good">{o.tp.toLocaleString()}</p><p className="quiet">true positives of {TEST_FRAUD.toLocaleString()} fraud ({(o.recall * 100).toFixed(1)}% recall)</p>
          <p className="fl-big warn">{o.fp.toLocaleString()}</p><p className="quiet">false positives ({(o.precision * 100).toFixed(1)}% precision)</p>
          <p className="quiet">Computed exactly from every ground-truth fraud’s saved rank. Nothing is interpolated.</p></div>
      </div>
    </div>
    <div className="fl-cols fl-explore">
      <div className="fl-card">
        <div className="fl-tabs" role="tablist" aria-label="Which rows to list">
          {([['top', 'Top ranked'], ['fp', 'False alarms'], ['fn', 'Missed fraud']] as [Filter, string][]).map(([key, label]) =>
            <button key={key} type="button" role="tab" aria-selected={filter === key} onClick={() => setF(key)}>{label}</button>)}
        </div>
        {!shown.length ? <p className="quiet">{filter === 'fp' && k > SAVED_TOP ? `False alarms below rank ${SAVED_TOP.toLocaleString()} are counted above but their rows are not saved.` : 'Nothing to list at this budget.'}</p> :
          <table className="fl-table fl-rows"><thead><tr><th>Rank</th><th>Model score</th><th>Ground truth</th><th>Outcome at {k.toLocaleString()}</th></tr></thead><tbody>
            {shown.map(r => { const out = outcomeOfRow(r, k); return <tr key={r.rank} className={pick === r.rank ? 'on' : ''} onClick={() => setPick(r.rank)}>
              <td><button type="button" className="rowlink" onClick={() => setPick(r.rank)} aria-label={`Inspect rank ${r.rank}`}>{r.rank.toLocaleString()}</button></td>
              <td><span className="scorebar" aria-hidden="true"><i style={{width: `${Math.max(1, r.score * 100)}%`}}/></span> {r.score.toFixed(4)}</td>
              <td>{r.fraud ? 'fraud' : 'not fraud'}</td><td><Chip tone={badge[out].tone}>{out}</Chip></td></tr>; })}</tbody></table>}
        <div className="pager" role="group" aria-label="Pages"><button className="iconbtn" aria-label="Previous page" disabled={cur === 0} onClick={() => setPage(cur - 1)}>‹</button>
          <span>{cur + 1} / {pages}</span><button className="iconbtn" aria-label="Next page" disabled={cur >= pages - 1} onClick={() => setPage(cur + 1)}>›</button></div>
        <p className="quiet">Saved: the top {SAVED_TOP.toLocaleString()} ranks and every fraud row. Other legitimate rows are counted, not listed.</p>
      </div>
      <div className="fl-card fl-trace" aria-live="polite">
        <h3>Trace one prediction</h3>
        {!row ? <p className="quiet">Select a row to follow it from input to outcome.</p> : <ol className="fl-steps">
          <li><b>1 · Raw input (saved fields)</b><span>step {row.step} · amount {row.amount.toFixed(2)} · customer code {row.customer} · merchant code {row.merchant} · category code {row.category}</span>
            <small className="quiet">Codes are the artifact’s integers. Names are not saved.</small></li>
          <li><b>2 · Engineered features</b><Chip tone="neutral">Evidence pending</Chip><small className="quiet">The saved artifact does not store feature vectors. The model team can supply them for chosen rows.</small></li>
          <li><b>3 · Model score</b><span className="scorebar" aria-hidden="true"><i style={{width: `${Math.max(1, row.score * 100)}%`}}/></span><span>{row.score.toFixed(6)}</span></li>
          <li><b>4 · Alert selection</b><span>{row.rank <= k ? 'Inside' : 'Outside'} the top {k.toLocaleString()} (rank {row.rank.toLocaleString()}).</span></li>
          <li><b>5 · Ground truth and outcome</b><span><Chip tone={row.fraud ? 'good' : 'neutral'}>{row.fraud ? 'Ground truth: fraud' : 'Ground truth: not fraud'}</Chip> <Chip tone={badge[outcomeOfRow(row, k)].tone}>{badge[outcomeOfRow(row, k)].text}</Chip></span>
            <small>{why(row, k, outcomeOfRow(row, k))}</small></li></ol>}
      </div>
    </div>
  </section>;
}
