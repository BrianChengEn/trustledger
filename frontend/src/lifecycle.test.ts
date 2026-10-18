import {describe, expect, it} from 'vitest';
import {ruleCoverage} from './lib';
import type {Transaction} from './api';
const tx: Transaction = {id:'test', account_token:'test', occurred_at:'2026-10-17T00:00:00Z',
  amount:300, currency:'USD', direction:'unknown', merchant_display:'Transfer', merchant_category:'other',
  source:'nessie', is_subscription:false};
describe('rule evidence semantics', () => {
  it('never calls missing direction safe', () => expect(ruleCoverage(tx)).toBe('Insufficient evidence'));
  it('distinguishes unavailable, not applicable, and evaluated without alert', () => {
    expect(ruleCoverage(tx, false)).toBe('Analysis unavailable');
    expect(ruleCoverage({...tx, direction:'credit'})).toBe('Rules not applicable');
    expect(ruleCoverage({...tx, direction:'debit', settlement_status:'pending'})).toBe('Rules not applicable');
    expect(ruleCoverage({...tx, direction:'debit', settlement_status:'completed'})).toBe('No rule triggered');
  });
});
