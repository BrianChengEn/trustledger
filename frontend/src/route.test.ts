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
  it('recovers from malformed encoded links inside the same customer context', () => {
    expect(parse(`#/sources/${customer}/case/%`)).toEqual({view: 'today', customer});
    expect(parse('#/case/%')).toEqual({view: 'today'});
  });
});
