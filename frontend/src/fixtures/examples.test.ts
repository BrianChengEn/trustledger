import {describe, expect, it} from 'vitest';
import {
  amountAlert, apiError, baselineTransactions, confirmation, confirmedNormalAlert, duplicateAlert,
  emptyTransactions,
  fallbackExplanation, fixtureMeta, geminiShapeExplanation, jevShapeAnalysis, loadingState,
  memoryConsent, privacyPreview, rulesOnlyAnalysis, subscriptionAlert, templateExplanation,
} from './examples';

describe('synthetic API fixtures', () => {
  it('stays marked as mock data and keeps the eight demo transactions', () => {
    expect(fixtureMeta.synthetic).toBe(true);
    expect(fixtureMeta.liveProviderVerified).toBe(false);
    expect(baselineTransactions).toHaveLength(18);
    expect(baselineTransactions.map((row) => row.id)).toEqual(expect.arrayContaining([
      'txn_syn_001', 'txn_syn_002', 'txn_syn_003', 'txn_syn_004',
      'txn_syn_005', 'txn_syn_006', 'txn_syn_007', 'txn_syn_008',
    ]));
  });

  it('covers the review states without claiming a live provider call', () => {
    expect(duplicateAlert.alert_type).toBe('duplicate');
    expect(amountAlert.status).toBe('open');
    expect(subscriptionAlert.alert_type).toBe('subscription_change');
    expect(confirmedNormalAlert.status).toBe('normal');
    expect(rulesOnlyAnalysis.provider_mode).toBe('rules-only');
    expect(jevShapeAnalysis.evidence[0]).toMatch(/^Synthetic fixture shape/);
    expect(templateExplanation.explanation_mode).toBe('template');
    expect(fallbackExplanation.explanation_mode).toBe('fallback');
    expect(fallbackExplanation.failure).toBe('timeout');
    expect(geminiShapeExplanation.why_flagged).toMatch(/^Synthetic shape example/);
    expect(geminiShapeExplanation.sent_to_provider).toBe(false);
    expect(Object.keys(privacyPreview.safe_payload)).toEqual([
      'merchant_category', 'amount_bucket', 'currency', 'local_day_part',
      'same_category_same_amount_24h_count', 'is_subscription',
      'subscription_delta_bucket', 'prior_user_confirmation',
    ]);
    expect(privacyPreview.safe_payload).not.toHaveProperty('merchant_display');
    expect(memoryConsent.source).toBe('local-fallback');
    expect(confirmation.decision).toBe('normal');
    expect(emptyTransactions).toEqual([]);
    expect(loadingState).toEqual({state: 'loading'});
    expect(apiError.error.code).toBe('not_found');
  });
});
