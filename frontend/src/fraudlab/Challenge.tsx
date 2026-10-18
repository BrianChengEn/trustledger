import {useState} from 'react';
import {Icon} from '../icons';
import {ConfusionGrid, Bars} from './charts';
import {BUDGET, HEADLINE, TEST_FRAUD, TEST_ROWS, evidence, expectedByChance, model, outcomeAt, predictAllLegitimate} from './data';

const pct = (v: number, d = 2) => (v * 100).toFixed(d) + '%';

/** Chapter 1: why accuracy misleads, and what a limited review team actually needs. */
export default function Challenge() {
  const [lazy, setLazy] = useState(false);
  const [k, setK] = useState(BUDGET);
  const legit = TEST_ROWS - TEST_FRAUD;
  const trap = predictAllLegitimate(legit, TEST_ROWS);
  const m = model(HEADLINE), o = outcomeAt(m, k), chance = expectedByChance(k);
  const full = evidence.dataset;
  return <section aria-labelledby="fl-title" className="fl-chapter">
    <h2 id="fl-title" className="visually-hidden">The fraud detection challenge</h2>
    <p className="fl-lede">Fraud is rare, so a model can look excellent while finding nothing.</p>
    <div className="fl-cols">
      <div className="fl-card">
        <h3>The real class balance</h3>
        <Bars label="Class balance in the test slice" max={TEST_ROWS} format={v => v.toLocaleString()} items={[
          {key: 'legit', label: 'Legitimate', value: legit, tone: 'ok', note: `${pct(legit / TEST_ROWS)} of the test slice`},
          {key: 'fraud', label: 'Fraud', value: TEST_FRAUD, tone: 'bad', note: `${pct(TEST_FRAUD / TEST_ROWS)} of the test slice`}]}/>
        <p className="quiet">Whole BankSim file: {full.rows.toLocaleString()} transactions, {full.fraud.toLocaleString()} fraud ({pct(full.fraud / full.rows)}). The test slice is steps 150–179.</p>
      </div>
      <div className="fl-card">
        <h3>What if a model calls everything legitimate?</h3>
        <label className="fl-toggle"><input type="checkbox" checked={lazy} onChange={e => setLazy(e.target.checked)}/>
          <span><b>Predict “legitimate” for every transaction</b><small>Counts come from the real test slice.</small></span></label>
        {lazy ? <div className="fl-trap" aria-live="polite">
          <p><strong>{pct(trap.accuracy)}</strong> accuracy</p>
          <p><strong>{pct(trap.fraudRecall, 0)}</strong> of fraud found, so all <b>{trap.missed.toLocaleString()}</b> fraud transactions are missed</p>
          <p className="quiet">High accuracy, zero usefulness. That is why this lab reports ranking quality (average precision) and results at a fixed alert budget instead.</p></div>
          : <p className="quiet">Turn it on to see the accuracy of a model that never finds fraud.</p>}
      </div>
    </div>
    <div className="fl-card">
      <h3>What a review team needs: find fraud without wasting reviews</h3>
      <div className="fl-slider"><label htmlFor="fl-k">Alerts the team can review: <b>{k.toLocaleString()}</b></label>
        <input id="fl-k" type="range" min={100} max={2000} step={1} value={k} onChange={e => setK(Number(e.target.value))}/>
        <div className="fl-presets">{[100, 500, BUDGET, 2000].map(n => <button key={n} type="button" aria-pressed={k === n} onClick={() => setK(n)}>{n}</button>)}</div></div>
      <div className="fl-cols">
        <div><h4>Picked at random</h4><p className="fl-big">{chance.toFixed(1)}</p><p className="quiet">fraud cases expected among {k.toLocaleString()} random alerts (computed from the base rate)</p></div>
        <div><h4>Ranked by the model</h4><p className="fl-big good">{o.tp.toLocaleString()}</p><p className="quiet">fraud cases actually found in the model’s top {k.toLocaleString()} (from saved scores and labels)</p></div>
      </div>
    </div>
    <div className="fl-cols">
      <div className="fl-card"><h4><Icon name="alertTriangle" size={16}/> False positive</h4><p>A legitimate transaction flagged as fraud.</p>
        <p className="quiet">Consequence: wasted investigation time, and possibly a blocked or questioned customer. At {k.toLocaleString()} alerts: <b>{o.fp}</b>.</p></div>
      <div className="fl-card"><h4><Icon name="eyeOff" size={16}/> False negative</h4><p>A fraudulent transaction the model did not flag.</p>
        <p className="quiet">Consequence: the loss goes undetected. At {k.toLocaleString()} alerts: <b>{o.fn.toLocaleString()}</b> of {TEST_FRAUD.toLocaleString()} fraud are not in the queue.</p></div>
    </div>
    <ConfusionGrid o={o}/>
    <p className="quiet">Why it matters: the alert budget fixes the workload. Every extra real fraud caught inside the budget means one fewer false alarm.</p>
  </section>;
}
