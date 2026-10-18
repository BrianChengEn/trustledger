import type {Alert, Confirmation, Health, Memory, Transaction} from './api';

export const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
export const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
export const fullDate = (iso: string) => new Date(iso).toLocaleString(undefined,
  {month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'});
export const prettyCategory = (name: string) => name.replaceAll('_', ' ');

export const alertHints: Record<Alert['alert_type'], string> = {
  duplicate: 'Same merchant and amount within 24 hours',
  amount_anomaly: 'Above the demo high-amount threshold',
  subscription_change: 'A recurring charge rose by more than 20%',
  none: 'No rule triggered',
};
const severityRank = {high: 0, medium: 1, low: 2} as const;
/** Open alerts first, then by severity, then by the larger amount. */
export function byPriority(alerts: Alert[], transactions: Transaction[]): Alert[] {
  const amount = (a: Alert) => transactions.find(t => t.id === a.transaction_id)?.amount ?? 0;
  return [...alerts].sort((a, b) =>
    Number(a.status !== 'open') - Number(b.status !== 'open')
    || severityRank[a.severity] - severityRank[b.severity] || amount(b) - amount(a));
}

/** The only sentence the backend will store; mirrors memory_policy.memory_sentence for display. */
export const memorySentence = (category: string) =>
  `The demo user explicitly confirmed a ${category} alert as normal. Recheck future evidence.`;
export const memoryCategory = (summary: string) =>
  /^The demo user explicitly confirmed a ([a-z_]+) alert as normal\./.exec(summary)?.[1] ?? null;
/** The backend adds this evidence line when a consented memory matched the category. */
export const isPriorEvidence = (text: string) => text.startsWith('A prior consented confirmation');

export type Tone = 'good' | 'warn' | 'neutral' | 'ai';
export const memoryStore = (source: Memory['source']): {label: string; detail: string; tone: Tone} =>
  source === 'backboard'
    ? {label: 'Backboard memory', detail: 'Stored with Backboard persistent memory.', tone: 'good'}
    : {label: 'Local fallback', detail: 'Stored in this app’s local SQLite database. Not on Backboard.', tone: 'neutral'};

export function memoryModeCopy(mode: Health['memory_mode'] | undefined): {label: string; detail: string; tone: Tone} {
  switch (mode) {
    case 'backboard-live': return {label: 'Backboard live', tone: 'good', detail: 'A Backboard memory call has succeeded in this server session. Each saved memory still shows where it is stored.'};
    case 'degraded': return {label: 'Memory degraded', tone: 'warn', detail: 'The last Backboard memory call did not complete. Each row keeps its own source label; an unconfirmed write is not reported as saved.'};
    case 'off': return {label: 'Memory off', tone: 'neutral', detail: 'Memory writes are disabled on this server. Decisions still work; nothing is remembered.'};
    case 'local-fallback': return {label: 'Local memory', tone: 'neutral', detail: 'No Backboard call has been confirmed this session. Memories are saved in local SQLite and labelled local fallback.'};
    default: return {label: 'Connecting…', tone: 'neutral', detail: 'Waiting for the server.'};
  }
}
export function dataModeCopy(mode: Health['data_mode'] | undefined): {label: string; detail: string; tone: Tone} {
  switch (mode) {
    case 'synthetic': return {label: 'Synthetic demo data', tone: 'neutral', detail: 'Fixture transactions stored in local SQLite. No real accounts or money.'};
    case 'nessie-live': return {label: 'Nessie sandbox', tone: 'good', detail: 'Transactions are read from the Capital One Nessie sandbox.'};
    case 'degraded': return {label: 'Data degraded', tone: 'warn', detail: 'The transaction source is not responding.'};
    default: return {label: 'Connecting…', tone: 'neutral', detail: 'Waiting for the server.'};
  }
}

export function outcomeCopy(c: Confirmation, source?: Memory['source']): {title: string; detail: string; tone: Tone} {
  switch (c.memory_status) {
    case 'written': return {title: 'Memory saved', tone: 'good', detail: source === 'backboard'
      ? 'Stored with Backboard persistent memory. You can delete it from Memory at any time.'
      : 'Stored in the local fallback database, not on Backboard. You can delete it from Memory at any time.'};
    case 'pending': return {title: 'Memory not confirmed yet', tone: 'warn',
      detail: 'Your decision is recorded, but the memory write has not been confirmed. Check Memory for its state.'};
    case 'failed': return {title: 'Memory not saved', tone: 'warn', detail: 'Your decision is recorded, but the memory could not be saved.'};
    case 'skipped': return {title: 'Nothing remembered', tone: 'neutral', detail: 'Memory did not apply to this confirmation.'};
    default: return {title: 'Nothing remembered', tone: 'neutral', detail: 'No memory was saved for this decision.'};
  }
}
