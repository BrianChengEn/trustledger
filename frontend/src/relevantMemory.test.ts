import {describe, expect, it} from 'vitest';
import {relevantMemoryCopy} from './lib';

describe('relevant memory wording', () => {
  it('claims a live Backboard search only when the backend reports one', () => {
    expect(relevantMemoryCopy({memory_status: 'backboard-live', retrieval: 'backboard-search', summary: 's'}).chip).toBe('Backboard · live search');
    expect(relevantMemoryCopy({memory_status: 'backboard-live', retrieval: 'category-filter', summary: 's'}).chip).toBe('Backboard memory');
  });
  it('never presents local fallback as a Backboard search', () => {
    const copy = relevantMemoryCopy({memory_status: 'local-fallback', retrieval: 'category-filter', summary: 's'});
    expect(copy.chip).toBe('Local fallback');
    expect(copy.detail).toMatch(/not a live Backboard search/);
  });
  it('separates a genuine empty result from an outage', () => {
    const none = relevantMemoryCopy({memory_status: 'no-relevant-memory', retrieval: null, summary: null});
    const down = relevantMemoryCopy({memory_status: 'unavailable', retrieval: null, summary: null});
    expect(none.title).toBe('No relevant memory found.');
    expect(down.title).toBe('Memory unavailable');
    expect(down.tone).toBe('warn');
    expect(none.hasMemory || down.hasMemory).toBe(false);
  });
});
