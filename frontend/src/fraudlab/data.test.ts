import {describe, expect, it} from 'vitest';
import {HEADLINE, TEST_FRAUD, TEST_ROWS, averagePrecision, evidence, expectedByChance, model, models, outcomeAt, outcomeOfRow, prCurve,
  predictAllLegitimate, provenance, rows} from './data';

describe('the verified headline (benchmark/leaderboard.json, reproduced from the saved scores)', () => {
  const m = model(HEADLINE);
  it('896 of the top 919 alerts are fraud, 23 are not', () => {
    const o = outcomeAt(m, 919);
    expect(o).toMatchObject({k: 919, tp: 896, fp: 23, fn: 304, tn: 110083});
    expect(o.precision).toBeCloseTo(0.975, 3);
    expect(o.recall).toBeCloseTo(896 / 1200, 6);
  });
  it('recall uses the test slice fraud count (1,200), not the full dataset (7,200)', () => {
    expect(TEST_FRAUD).toBe(1200); expect(evidence.dataset.fraud).toBe(7200);
    expect(outcomeAt(m, 919).recall).toBeCloseTo(0.7467, 3);
  });
  it('average precision from the saved ranking matches the reported 0.957628', () => {
    expect(m.average_precision).toBeCloseTo(0.957628, 6);
    expect(Math.abs(averagePrecision(m) - m.average_precision)).toBeLessThan(2e-5);
  });
});

describe('every model reproduces its published confusion counts at the 919 budget', () => {
  for (const m of models) {
    it(m.model, () => {
      const o = outcomeAt(m, 919);
      expect([o.tp, o.fp, o.fn, o.tn]).toEqual([m.TP, m.FP, m.FN, m.TN]);
      expect(m.fraud_ranks).toHaveLength(TEST_FRAUD);
      expect(m.fraud_ranks.every((r, i) => i === 0 || r > m.fraud_ranks[i - 1])).toBe(true);
      expect(m.fraud_ranks[m.fraud_ranks.length - 1]).toBeLessThanOrEqual(TEST_ROWS);
    });
  }
});

describe('alert budget is exact, never interpolated', () => {
  const m = model(HEADLINE);
  it('TP + FP equals the budget and TP + FN equals the fraud count at every budget', () => {
    for (const k of [0, 1, 100, 500, 919, 2000, 5000, TEST_ROWS]) {
      const o = outcomeAt(m, k);
      expect(o.tp + o.fp).toBe(k); expect(o.tp + o.fn).toBe(TEST_FRAUD); expect(o.fp + o.tn).toBe(TEST_ROWS - TEST_FRAUD);
    }
  });
  it('true positives never decrease as the budget grows', () => {
    let last = -1;
    for (let k = 0; k <= 3000; k += 37) { const tp = outcomeAt(m, k).tp; expect(tp).toBeGreaterThanOrEqual(last); last = tp; }
  });
  it('reviewing every row finds every fraud', () => expect(outcomeAt(m, TEST_ROWS).tp).toBe(TEST_FRAUD));
});

describe('PR curve vertices are exact', () => {
  it('recall rises one fraud at a time and precision stays in (0, 1]', () => {
    const c = prCurve(model(HEADLINE));
    expect(c).toHaveLength(TEST_FRAUD); expect(c[c.length - 1].recall).toBe(1);
    expect(c.every((p, i) => p.precision > 0 && p.precision <= 1 && (i === 0 || p.recall > c[i - 1].recall))).toBe(true);
  });
});

describe('saved rows (ground truth, score and outcome are separate things)', () => {
  it('are in rank order with non-increasing scores', () => {
    expect(rows.every((r, i) => i === 0 || (r.rank > rows[i - 1].rank && r.score <= rows[i - 1].score + 1e-9))).toBe(true);
  });
  it('contain every ground-truth fraud, consistent with the headline ranking', () => {
    const fraud = rows.filter(r => r.fraud).map(r => r.rank);
    expect(fraud).toEqual(model(HEADLINE).fraud_ranks);
  });
  it('contain the whole top 1,200 without gaps', () => {
    for (let i = 0; i < 1200; i++) expect(rows[i].rank).toBe(i + 1);
  });
  it('label each row TP, FP, FN or TN from its own label and rank only', () => {
    expect(outcomeOfRow(rows[0], 919)).toBe(rows[0].fraud ? 'TP' : 'FP');
    expect(rows.filter(r => outcomeOfRow(r, 919) === 'FP')).toHaveLength(23);
    expect(rows.filter(r => outcomeOfRow(r, 919) === 'TP')).toHaveLength(896);
    expect(rows.filter(r => outcomeOfRow(r, 919) === 'FN')).toHaveLength(304);
  });
});

describe('class balance and the "predict everything legitimate" trap', () => {
  it('the splits add up to the dataset', () => {
    const c = evidence.splits.counts;
    expect(c.train.rows + c.selection.rows + c.confirm.rows + c.test.rows).toBe(evidence.dataset.rows);
    expect(c.train.fraud + c.selection.fraud + c.confirm.fraud + c.test.fraud).toBe(evidence.dataset.fraud);
  });
  it('predicting all legitimate on the test slice: 98.9% accurate, 0% fraud found', () => {
    const r = predictAllLegitimate(TEST_ROWS - TEST_FRAUD, TEST_ROWS);
    expect(r.accuracy).toBeCloseTo(0.98922, 4); expect(r.fraudRecall).toBe(0); expect(r.missed).toBe(1200);
  });
  it('random review of 919 alerts is expected to find about 10 fraud', () => expect(expectedByChance(919)).toBeCloseTo(9.9, 1));
});

describe('provenance', () => {
  it('records a SHA-256 for every source artifact', () => {
    const hashes = Object.values(provenance.sources_sha256);
    expect(hashes.length).toBeGreaterThan(16);
    expect(hashes.every(h => /^[0-9a-f]{64}$/.test(h))).toBe(true);
  });
});
