import {describe, expect, it} from 'vitest';
import type {Alert, Movement} from './api';
import {backboardBody, duplicateChecks, earlierTwin, gapText, isDuplicate, pickStory, reasonCodes} from './story';

const tx = (id: string, iso: string, o: Partial<Movement> = {}): Movement => ({
  id, occurred_at: iso, amount: 11.99, currency: 'USD', direction: 'debit', merchant_display: 'StreamWave',
  merchant_category: 'streaming', source: 'synthetic', account_token: 'acct_demo_a1', is_subscription: true,
  kind: 'purchase', settlement_status: 'completed', date_only: false, ...o});
const alert = (id: string, type: Alert['alert_type'] = 'duplicate'): Alert => ({
  alert_id: 'alert_' + id, transaction_id: id, alert_type: type, severity: 'medium', needs_human: true, confidence: 1,
  evidence: [], provider_mode: 'rules-only', model_version: null, request_id: 'r', status: 'open'});

const t003 = tx('txn_syn_003', '2026-10-17T13:57:00-04:00'), t004 = tx('txn_syn_004', '2026-10-17T14:03:00-04:00');
const t009 = tx('txn_syn_009', '2026-10-17T16:00:00-04:00');

describe('duplicate rule conditions (mirrors backend/app/core/rules.py)', () => {
  it('003 and 004 satisfy all four conditions with the real 6 minute gap', () => {
    const c = duplicateChecks(t004, t003);
    expect(c).toEqual({merchant: true, amount: true, within24h: true, debit: true, gapMinutes: 6});
    expect(isDuplicate(c)).toBe(true);
  });
  it('fails when the amount differs, the gap is over 24 hours, or the later charge is a refund', () => {
    expect(isDuplicate(duplicateChecks(tx('a', t004.occurred_at, {amount: 12}), t003))).toBe(false);
    expect(isDuplicate(duplicateChecks(tx('b', '2026-10-19T14:03:00-04:00'), t003))).toBe(false);
    expect(isDuplicate(duplicateChecks(tx('c', t004.occurred_at, {direction: 'credit'}), t003))).toBe(false);
  });
  it('never treats an earlier transaction as a later one', () => {
    expect(isDuplicate(duplicateChecks(t003, t004))).toBe(false);
  });
  it('finds the nearest earlier twin', () => {
    expect(earlierTwin(t004, [t003, t004])?.id).toBe('txn_syn_003');
    expect(earlierTwin(t009, [t003, t004, t009])?.id).toBe('txn_syn_004');
    expect(earlierTwin(t003, [t003, t004])).toBeNull();
  });
  it('formats gaps without inventing precision', () => {
    expect(gapText(6)).toBe('6 minutes'); expect(gapText(1)).toBe('1 minute'); expect(gapText(120)).toBe('2 hours');
    expect(gapText(125)).toBe('2 h 5 min'); expect(gapText(null)).toBe('unknown');
  });
});

describe('story selection uses only real records', () => {
  it('uses 004 with its twin 003, and 009 as the later alert when it exists', () => {
    const s = pickStory([t003, t004, t009], [alert('txn_syn_004'), alert('txn_syn_009')]);
    expect(s?.tx.id).toBe('txn_syn_004'); expect(s?.twin.id).toBe('txn_syn_003'); expect(s?.later?.tx.id).toBe('txn_syn_009');
  });
  it('has no later alert (and invents none) when the data has only the first pair', () => {
    const s = pickStory([t003, t004], [alert('txn_syn_004')]);
    expect(s?.later).toBeNull();
  });
  it('returns null when nothing is a duplicate', () => {
    expect(pickStory([t003], [alert('txn_syn_003', 'amount_anomaly')])).toBeNull();
  });
  it('ignores a later alert from a different category', () => {
    const other = tx('x', '2026-10-17T17:00:00-04:00', {merchant_category: 'dining'});
    expect(pickStory([t003, t004, other], [alert('txn_syn_004'), alert('x')])?.later).toBeNull();
  });
});

describe('Gemini reason codes mirror the backend', () => {
  const features = {merchant_category: 'streaming', amount_bucket: '10-25', currency: 'USD', local_day_part: 'afternoon',
    same_category_same_amount_24h_count: 2, is_subscription: true, subscription_delta_bucket: 'none', prior_user_confirmation: 'unknown'};
  it('duplicate with two matches', () => {
    expect(reasonCodes('duplicate', true, features)).toEqual(['same_category_same_amount_within_24h', 'human_review_required',
      'recurring_subscription', 'subscription_delta_none']);
  });
  it('adds the prior-confirmation code only for a consented normal memory', () => {
    expect(reasonCodes('duplicate', true, {...features, prior_user_confirmation: 'normal'})).toContain('prior_category_confirmation_normal');
    expect(reasonCodes('duplicate', true, features)).not.toContain('prior_category_confirmation_normal');
  });
});

describe('Backboard body', () => {
  it('is exactly the approved category sentence and nothing else', () => {
    expect(backboardBody('streaming')).toEqual({content: 'The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence.'});
    expect(JSON.stringify(backboardBody('streaming'))).not.toMatch(/StreamWave|11\.99|acct_|txn_/);
  });
});
