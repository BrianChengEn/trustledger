import {describe, expect, it} from 'vitest';
import {href, parse} from './route';

describe('customer navigation stays inside Data sources', () => {
  const customer = 'customer_' + 'a'.repeat(32);
  it('opens customer Activity without changing the main workspace route', () => {
    expect(parse(`#/sources/${customer}/activity`)).toEqual({view: 'activity', customer});
    expect(href({view: 'activity'})).toBe('#/activity');
  });
  it('round-trips Activity shortcut filters in the current workspace', () => {
    for (const filter of ['flagged', 'recurring']) {
      expect(parse(`#/activity/${filter}`)).toEqual({view: 'activity', filter});
      expect(href({view: 'activity', filter})).toBe(`#/activity/${filter}`);
      expect(parse(`#/sources/${customer}/activity/${filter}`))
        .toEqual({view: 'activity', filter, customer});
      expect(href({view: 'activity', filter, customer})).toBe(`#/sources/${customer}/activity/${filter}`);
    }
  });
  it('keeps case and privacy links in their customer namespace', () => {
    expect(parse(href({view: 'case', tx: 'txn/a b', from: 'activity', customer})))
      .toEqual({view: 'case', tx: 'txn/a b', from: 'activity', customer});
    expect(parse(href({view: 'privacy', tx: 'txn/a b', customer})))
      .toEqual({view: 'privacy', tx: 'txn/a b', customer});
    expect(href({view: 'sources', customer})).toBe('#/sources');
  });
  it('round-trips the admin demo-data pages', () => {
    expect(parse('#/admin')).toEqual({view: 'admin'});
    expect(parse('#/admin/log')).toEqual({view: 'admin', tab: 'log'});
    expect(href({view: 'admin'})).toBe('#/admin');
    expect(href({view: 'admin', tab: 'log'})).toBe('#/admin/log');
    expect(parse('#/admin/%')).toEqual({view: 'today'});
  });
  it('recovers from malformed encoded links inside the same customer context', () => {
    expect(parse(`#/sources/${customer}/case/%`)).toEqual({view: 'today', customer});
    expect(parse('#/case/%')).toEqual({view: 'today'});
  });
  it('round-trips the Memory and Privacy lab routes', () => {
    expect(parse('#/memory')).toEqual({view: 'memory'});
    expect(parse('#/memory/lab')).toEqual({view: 'memory', lab: ''});
    expect(parse('#/memory/lab/l1-5')).toEqual({view: 'memory', lab: 'l1-5'});
    expect(href({view: 'memory', lab: 'l2-3'})).toBe('#/memory/lab/l2-3');
    expect(href({view: 'memory', lab: ''})).toBe('#/memory/lab');
    expect(parse('#/privacy/lab/p-4')).toEqual({view: 'privacy', lab: 'p-4'});
    expect(href({view: 'privacy', lab: 'p-4'})).toBe('#/privacy/lab/p-4');
    expect(parse('#/privacy/txn_syn_004')).toEqual({view: 'privacy', tx: 'txn_syn_004'});
  });
});
