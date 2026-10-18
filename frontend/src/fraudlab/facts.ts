/** Facts that are documented in the research text rather than stored as numbers. Each carries its source file, and facts.test.ts
 *  checks the quoted values really appear in that file. */
export const SRC = {
  protocol: 'evaluation/research/benchmark/PROTOCOL.txt',
  findings: 'evaluation/research/benchmark/FINDINGS.txt',
  v2: 'evaluation/research/v2/FINDINGS.txt',
  leakage: 'evaluation/research/benchmark/trustledger/NOTES.txt',
  audit: 'evaluation/research/benchmark/audit/AUDIT.txt',
  shortlist: 'evaluation/research/benchmark/discovery/SHORTLIST.txt',
  leaderboard: 'evaluation/research/benchmark/leaderboard.json',
  framework: 'evaluation/research/v2/results/framework_v2.json',
} as const;

/** Own-label leakage in the original merchant fraud rate (NOTES.txt). Strings are kept exactly as written in the source. */
export const ownLabelGap = {trainMean: '1.9636312546803278e-05', fraudRows: '0.0008757162664799481', max: '0.013641193354449077'};

/** Further leakage-audit numbers quoted from NOTES.txt (shown with thousands separators; the source writes them without). */
export const leakFacts = {laterRows: '371,371 of 374,914', laterRowsSource: '371371 / 374914', testMaxDiff: '0.0', unseenTestMerchants: '0'};

export interface FeatureGroup {name: string; what: string; how: string; why: string; atT: string; leakage: string}
/** Feature groups as listed in v2/FINDINGS.txt. Exact formulas live in evaluation/research/v2/run_framework.py. */
export const featureGroups: FeatureGroup[] = [
  {name: 'Amount', what: 'The size of the charge, on a log scale.', how: 'Log of the transaction amount.',
    why: 'Fraud in BankSim tends to involve larger amounts than the same customer’s usual spending.', atT: 'Yes: it is on the transaction itself.', leakage: 'None.'},
  {name: 'Customer history', what: 'How much history this customer has, and how this charge compares with it.',
    how: 'The count of the customer’s earlier rows, the amount relative to their own average, and a customer z-score.',
    why: 'A charge that is unusual for this customer stands out even if it is small in absolute terms.',
    atT: 'Yes, but only earlier rows. Same-step order follows the file order.', leakage: 'Guarded: customer history looks only at earlier rows.'},
  {name: 'New merchant, recency', what: 'Whether this customer has used this merchant before, and steps since their previous charge.',
    how: 'A flag for a new merchant for this customer, and the step gap to the customer’s previous row.', why: 'Sudden new merchants and bursts of activity are common fraud signals.',
    atT: 'Yes: earlier rows only.', leakage: 'Guarded: uses only earlier rows.'},
  {name: 'Repeat within 24 hours', what: 'The same merchant and amount repeated within a day.', how: 'A count of earlier rows with the same merchant and amount within 24 hours.',
    why: 'It is the same idea as the product’s duplicate rule, learned rather than hard-coded.', atT: 'Yes: earlier rows only.', leakage: 'Guarded.'},
  {name: 'Activity windows', what: 'How busy the customer is right now.', how: 'Row counts in the same step and the last 7 steps, and a ratio to the customer’s 30-step median amount.',
    why: 'Bursts and sudden jumps in spending are informative.', atT: 'Yes: earlier rows only.', leakage: 'Guarded: windows end before this row.'},
  {name: 'BankSim category', what: 'The dataset’s original merchant category (not the product’s coarse categories).', how: 'The raw category, plus a category amount CDF and a multiple of the category median.',
    why: 'What counts as a large amount depends heavily on the category.', atT: 'Yes: the category is on the transaction; the CDF and median come from training steps 0–119.',
    leakage: 'Guarded: category statistics use training-period legitimate transactions only.'},
  {name: 'Merchant fraud rate (merchant-aware arm)', what: 'How often a merchant was involved in fraud during training.',
    how: 'The merchant’s fraud rate over steps 0–119, shrunk toward the overall rate (alpha 20).', why: 'It is by far the strongest single signal in this simulator.',
    atT: 'Only the frozen training-period rate, never a later one.', leakage: 'The risky one. The original version leaked a row’s own label; the step-causal version removes that.'},
];

export interface Reference {who: string; what: string; why: string; source: string}
/** Published numbers from public repositories. They use other splits or metrics, so they are never plotted against ours. */
export const references: Reference[] = [
  {who: 'atavci (2019): soft-vote ensemble', what: 'Class-1 precision 0.73, recall 0.81 (2,160 test fraud)',
    why: 'Random stratified split of the whole file and a different metric; not the same test rows.', source: SRC.shortlist},
  {who: 'atavci (2019): KNN', what: 'Class-1 precision 0.83, recall 0.61',
    why: 'Random stratified split and a threshold-based report, not a ranking under an alert budget.', source: SRC.shortlist},
  {who: '0xSushmitha (2025): LightGBM', what: 'Published AUPRC 0.9578',
    why: 'Their own protocol (a step ≤ 600 cut that does not exist in the canonical 0–179 file). Not the number we measured under our split.', source: SRC.findings},
];

export const publicSources = [
  {name: 'atavci / turkayavci (2019)', url: 'https://github.com/atavci/fraud-detection-on-banksim-data/blob/master/Fraud_Detection_bank_sim.py'},
  {name: 'atavci notebook on Kaggle (title only was readable)', url: 'https://www.kaggle.com/code/turkayavci/fraud-detection-on-bank-payments/notebook'},
  {name: '0xSushmitha (2025)', url: 'https://github.com/0xSushmitha/Fraud-detection-in-financial-Transactions'},
];

export const CHAPTERS = [
  {id: 'overview', short: 'Overview', title: 'Overview'},
  {id: 'challenge', short: '1 · The challenge', title: 'The fraud detection challenge'},
  {id: 'features', short: '2 · Data & features', title: 'Data and feature engineering'},
  {id: 'architecture', short: '3 · Architecture', title: 'Model architecture'},
  {id: 'evaluation', short: '4 · Training & evaluation', title: 'Training and evaluation'},
  {id: 'explorer', short: '5 · Prediction explorer', title: 'Interactive prediction analysis'},
  {id: 'arena', short: '6 · Benchmark arena', title: 'Benchmark comparison'},
] as const;
export type ChapterId = typeof CHAPTERS[number]['id'];
