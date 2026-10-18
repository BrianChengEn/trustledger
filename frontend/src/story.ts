import type {Alert, Movement, PrivacyPreview} from './api';
import {memorySentence} from './lib';

/** The four conditions of the duplicate rule in backend/app/core/rules.py, evaluated on two real transactions. */
export interface DuplicateChecks {
  merchant: boolean; amount: boolean; within24h: boolean; debit: boolean; gapMinutes: number | null;
}
export function duplicateChecks(later: Movement, earlier: Movement): DuplicateChecks {
  const gap = (new Date(later.occurred_at).getTime() - new Date(earlier.occurred_at).getTime()) / 60000;
  return {
    merchant: later.merchant_display === earlier.merchant_display,
    amount: later.amount === earlier.amount,
    within24h: gap >= 0 && gap <= 24 * 60,
    debit: later.direction === 'debit',
    gapMinutes: Number.isFinite(gap) ? Math.round(gap) : null,
  };
}
export const isDuplicate = (c: DuplicateChecks) => c.merchant && c.amount && c.within24h && c.debit;

/** The nearest earlier transaction that makes `tx` a duplicate, if any. */
export function earlierTwin(tx: Movement, all: Movement[]): Movement | null {
  const found = all.filter(o => o.id !== tx.id && isDuplicate(duplicateChecks(tx, o)))
    .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime());
  return found[0] ?? null;
}

export function gapText(minutes: number | null): string {
  if (minutes === null) return 'unknown';
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} hour${h === 1 ? '' : 's'}`;
}

export interface Story {
  tx: Movement; alert: Alert; twin: Movement; category: string;
  /** A later duplicate alert in the same category (txn_syn_009 in the Level 2 database), or null if the data has none. */
  later: {tx: Movement; alert: Alert} | null;
}

/** Picks the story from real workspace data only. Prefers txn_syn_004 and txn_syn_009; never invents a record. */
export function pickStory(transactions: Movement[], alerts: Alert[]): Story | null {
  const at = (t: Movement) => new Date(t.occurred_at).getTime();
  const candidates = alerts.filter(a => a.alert_type === 'duplicate')
    .map(a => ({alert: a, tx: transactions.find(t => t.id === a.transaction_id)}))
    .filter((c): c is {alert: Alert; tx: Movement} => !!c.tx)
    .map(c => ({...c, twin: earlierTwin(c.tx, transactions)}))
    .filter((c): c is {alert: Alert; tx: Movement; twin: Movement} => !!c.twin);
  if (!candidates.length) return null;
  const main = candidates.find(c => c.tx.id === 'txn_syn_004') ?? [...candidates].sort((a, b) => at(a.tx) - at(b.tx))[0];
  const laterAll = alerts.filter(a => a.alert_type === 'duplicate' && a.transaction_id !== main.tx.id)
    .map(a => ({alert: a, tx: transactions.find(t => t.id === a.transaction_id)}))
    .filter((c): c is {alert: Alert; tx: Movement} => !!c.tx && c.tx.merchant_category === main.tx.merchant_category && at(c.tx) > at(main.tx))
    .sort((a, b) => Number(b.tx.id === 'txn_syn_009') - Number(a.tx.id === 'txn_syn_009') || at(a.tx) - at(b.tx));
  return {tx: main.tx, alert: main.alert, twin: main.twin, category: main.tx.merchant_category,
    later: laterAll[0] ? {tx: laterAll[0].tx, alert: laterAll[0].alert} : null};
}

/** Mirror of reason_codes() in backend/app/services/ai/gemini_explanation.py, for the Privacy Lab's Gemini preview. */
export function reasonCodes(alertType: Alert['alert_type'], needsHuman: boolean, f: PrivacyPreview['safe_payload']): string[] {
  const primary = {duplicate: 'duplicate_rule_matched', amount_anomaly: 'amount_anomaly_rule_matched',
    subscription_change: 'subscription_rule_matched', none: 'no_demo_rule_matched'}[alertType];
  const specific = {duplicate: 'same_category_same_amount_within_24h', amount_anomaly: 'amount_bucket_at_or_above_demo_threshold',
    subscription_change: 'subscription_increase_over_20_percent', none: ''}[alertType];
  const supported = alertType === 'duplicate' ? Number(f.same_category_same_amount_24h_count) >= 2
    : alertType === 'amount_anomaly' ? f.amount_bucket === '250+'
    : alertType === 'subscription_change' ? f.subscription_delta_bucket === 'over-20-percent' : false;
  const codes = [supported && specific ? specific : primary, needsHuman ? 'human_review_required' : 'human_review_not_required'];
  if (f.prior_user_confirmation === 'normal') codes.push('prior_category_confirmation_normal');
  else if (f.prior_user_confirmation === 'review') codes.push('prior_category_confirmation_review');
  if (f.is_subscription) {
    codes.push('recurring_subscription');
    codes.push({'over-20-percent': 'subscription_delta_over_20_percent', 'up-to-20-percent': 'subscription_delta_up_to_20_percent',
      none: 'subscription_delta_none', unknown: 'subscription_delta_unknown'}[String(f.subscription_delta_bucket)] ?? 'subscription_delta_unknown');
  }
  return codes;
}

/** The only body ever sent to Backboard for a memory write (backboard_client.add_memory). */
export const backboardBody = (category: string) => ({content: memorySentence(category)});
