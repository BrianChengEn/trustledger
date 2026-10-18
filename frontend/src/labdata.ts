import {money, type Movement} from './api';
import type {TField} from './Lab';
import {prettyCategory} from './lib';

/** The six facts behind a memory event. Same list in Memory Lab step 5 and Privacy Lab (Backboard), so they never disagree. */
export function memoryFacts(tx: Movement, category: string): TField[] {
  return [
    {key: 'merchant', label: 'Merchant', value: tx.merchant_display, verdict: 'removed',
      reason: 'Not necessary for a category-level memory.', exposure: 'A merchant name shows where you spend and can help identify you.'},
    {key: 'amount', label: 'Exact amount', value: money(tx.amount), verdict: 'removed',
      reason: 'The memory does not need the precise financial value.', exposure: 'An exact amount can be matched to one specific bill or purchase.'},
    {key: 'account', label: 'Account identifier', value: tx.account_token, verdict: 'removed',
      reason: 'Not necessary for future category-level context.', exposure: 'An account identifier ties the memory to one account.'},
    {key: 'id', label: 'Transaction ID', value: tx.id, verdict: 'removed',
      reason: 'Not necessary in the external memory sentence.', exposure: 'A transaction ID points at one exact record.'},
    {key: 'category', label: 'Category', value: prettyCategory(category), verdict: 'retained', becomes: `“${category}”`,
      reason: 'Needed to describe the event and to match a later alert in the same category.', exposure: 'Limited: it shows the kind of spending, not where or how much.'},
    {key: 'decision', label: 'Confirmed normal decision', value: 'Normal (you confirmed)', verdict: 'retained', becomes: '“explicitly confirmed … as normal”',
      reason: 'The event records what you previously confirmed.', exposure: 'Limited: it shows you judged an alert in this category normal.'},
  ];
}

/** Why a field is treated the way it is, in plain words, keyed by the backend's field names. */
export const exposureByField: Record<string, string> = {
  'id / account_token': 'Identifiers point at one exact record and account.',
  merchant_display: 'A merchant name shows where you spend and can help identify you.',
  merchant_category: 'Limited: the kind of spending, not where or how much.',
  amount: 'An exact amount can be matched to one specific bill or purchase.',
  occurred_at: 'An exact time can be matched to one specific event.',
  prior_user_confirmation: 'Limited: only whether you previously confirmed this category.',
  'unknown fields / PII / API keys': 'Anything not approved could contain personal data or secrets.',
};
