import type {Alert, Confirmation, Explanation, Health, Memory, RelevantMemoryResult, Transaction} from './api';

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

/** Labels explanation provenance. Template and fallback text are never called Gemini output. */
export function explanationModeCopy(mode: Explanation['explanation_mode'], fromCache: boolean):
  {title: string; detail: string; tone: Tone} {
  if (mode === 'gemini-live' && fromCache) return {
    title: 'Gemini explanation reused', tone: 'ai',
    detail: 'This text came from Gemini earlier in this session. No new Gemini call was made.',
  };
  if (mode === 'gemini-live') return {
    title: 'Live Gemini explanation', tone: 'ai',
    detail: 'Gemini wrote this from the privacy-safe summary. It does not decide whether the charge is fraud.',
  };
  if (mode === 'fallback') return {
    title: 'Rules explanation', tone: 'warn',
    detail: 'Gemini did not return a usable explanation. This text comes from the rules, not from Gemini.',
  };
  return {
    title: 'Rules explanation', tone: 'neutral',
    detail: 'Gemini was not called. This text is written from the rules and the privacy-safe summary.',
  };
}

export interface RelevantMemoryCopy {title: string; chip: string; detail: string; tone: Tone; hasMemory: boolean}
/** Wording for each relevant-memory state. Never claims a live Backboard search unless the backend says so. */
export function relevantMemoryCopy(r: Pick<RelevantMemoryResult, 'memory_status' | 'retrieval' | 'summary'>): RelevantMemoryCopy {
  switch (r.memory_status) {
    case 'backboard-live': return {hasMemory: !!r.summary, tone: 'good', title: 'Relevant memory found',
      chip: r.retrieval === 'backboard-search' ? 'Backboard · live search' : 'Backboard memory',
      detail: r.retrieval === 'backboard-search' ? 'Retrieved from Backboard by a live search for this category.' : 'Stored with Backboard.'};
    case 'local-fallback': return {hasMemory: !!r.summary, tone: 'neutral', title: 'Relevant memory found (local)',
      chip: 'Local fallback', detail: 'Found in this app’s local records. This was not a live Backboard search.'};
    case 'no-relevant-memory': return {hasMemory: false, tone: 'neutral', title: 'No relevant memory found.', chip: 'Checked',
      detail: 'Nothing you consented to matches this category. This is a genuine empty result, not an outage.'};
    default: return {hasMemory: false, tone: 'warn', title: 'Memory unavailable', chip: 'Unavailable',
      detail: 'Memory could not be checked right now, which is not the same as having none. The alert and its evidence are unaffected.'};
  }
}
