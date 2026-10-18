import evidenceJson from './data/evidence.json';
import modelsJson from './data/models.json';
import provenanceJson from './data/provenance.json';
import rowsJson from './data/rows.json';

/** Everything here comes from the saved BankSim benchmark artifacts (see data/provenance.json). Nothing is typed in by hand. */
export interface ModelResult {
  model: string; track: 'A' | 'B' | null; fidelity: string; architecture: string | null; leakage_status: string | null; source_url: string | null;
  average_precision: number; roc_auc: number; TP: number; FP: number; FN: number; TN: number; precision: number; recall: number; alerts: number;
  score_unique_values: number; curve_ok: boolean; ap_protocol_order: number;
  /** 1-based rank of each ground-truth fraud row in the protocol's ranking (score, then amount, then row index). */
  fraud_ranks: number[];
}
export const models = modelsJson as ModelResult[];
export const evidence = evidenceJson as typeof evidenceJson & {bootstrap: Record<string, {block_count: number;
  ap_difference: {mean: number; ci95_low: number; ci95_high: number; includes_zero: boolean}}>};
export const provenance = provenanceJson;

export const HEADLINE = 'v2_merchant_step_causal';
export const model = (name: string) => {
  const found = models.find(m => m.model === name);
  if (!found) throw new Error('unknown model ' + name);
  return found;
};

/** One saved test row, in rank order. The ground-truth label is data about the row, never an input to any model. */
export interface RankedRow {
  rank: number; score: number; fraud: boolean; amount: number; step: number; customer: number; merchant: number; category: number;
}
export const rows: RankedRow[] = (rowsJson as number[][]).map(([rank, score, y, amount, step, customer, merchant, category]) =>
  ({rank, score, fraud: y === 1, amount, step, customer, merchant, category}));
export const rowAtRank = (rank: number) => rows.find(r => r.rank === rank);

export const TEST_ROWS = evidence.test_rows, TEST_FRAUD = evidence.test_fraud, BUDGET = evidence.budget;

/** The four outcomes of reviewing the top `k` alerts. Exact for any k: it counts ground-truth fraud ranks, nothing is interpolated. */
export interface Outcome {k: number; tp: number; fp: number; fn: number; tn: number; precision: number; recall: number}
export function outcomeAt(m: ModelResult, k: number): Outcome {
  const kk = Math.max(0, Math.min(TEST_ROWS, Math.round(k)));
  // fraud_ranks is sorted ascending: binary search for how many frauds rank within the top k.
  let lo = 0, hi = m.fraud_ranks.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (m.fraud_ranks[mid] <= kk) lo = mid + 1; else hi = mid; }
  const tp = lo, fp = kk - tp, fn = TEST_FRAUD - tp, tn = TEST_ROWS - TEST_FRAUD - fp;
  return {k: kk, tp, fp, fn, tn, precision: kk ? tp / kk : 0, recall: tp / TEST_FRAUD};
}

/** Exact precision-recall vertices: one per ground-truth fraud, at the rank where it is found. */
export const prCurve = (m: ModelResult) => m.fraud_ranks.map((rank, i) => ({recall: (i + 1) / TEST_FRAUD, precision: (i + 1) / rank, rank}));
/** Average precision in the protocol's ranking order (matches the published value for models with real scores). */
export const averagePrecision = (m: ModelResult) => m.fraud_ranks.reduce((sum, rank, i) => sum + (i + 1) / rank, 0) / TEST_FRAUD;

/** What happens if every transaction is called legitimate. */
export function predictAllLegitimate(legit: number, total: number) {
  return {accuracy: legit / total, fraudRecall: 0, missed: total - legit};
}
/** Fraud expected among k alerts picked at random from the test slice. */
export const expectedByChance = (k: number) => k * TEST_FRAUD / TEST_ROWS;

export type Outcome4 = 'TP' | 'FP' | 'FN' | 'TN';
/** A saved row's outcome at budget k. Rows outside the saved set are never asked about. */
export const outcomeOfRow = (row: RankedRow, k: number): Outcome4 => row.rank <= k ? (row.fraud ? 'TP' : 'FP') : (row.fraud ? 'FN' : 'TN');
