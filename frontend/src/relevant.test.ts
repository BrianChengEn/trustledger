import {describe, expect, it} from 'vitest';
import {relevantView, verificationLine} from './relevant';
import type {RelevantMemories} from './api';

const m = (verification: 'remote_verified' | 'local_only' | 'unverified') => ({
  memory_id: 'mem_1', summary: 'The demo user explicitly confirmed a streaming alert as normal. Recheck future evidence.',
  source: 'backboard', created_at: '2026-10-18T12:00:00Z', verification});
const body = (over: Partial<RelevantMemories>): RelevantMemories =>
  ({memories: [], retrieval_mode: 'local_fallback', checked_at: null, failure: null, ...over});

describe('relevant memory card states', () => {
  it('loading before any result', () => expect(relevantView(null, false)).toEqual({kind: 'loading'}));
  it('an HTTP error shows no memory', () => expect(relevantView(body({memories: [m('local_only')]}), true)).toEqual({kind: 'error'}));
  it('an empty list is never a match, even when the mode says remote_verified', () => {
    expect(relevantView(body({retrieval_mode: 'remote_verified'}), false)).toEqual({kind: 'empty'});
    expect(relevantView(body({}), false)).toEqual({kind: 'empty'});
  });
  it('unavailable shows no old summary even if rows were returned', () => {
    expect(relevantView(body({retrieval_mode: 'unavailable', memories: [m('unverified')]}), false)).toEqual({kind: 'unavailable'});
  });
  it('shows a found memory with its own verification wording', () => {
    const v = relevantView(body({retrieval_mode: 'remote_verified', memories: [m('remote_verified')]}), false);
    expect(v.kind).toBe('found');
    expect(verificationLine('remote_verified')).toBe('Checked with Backboard just now.');
    expect(verificationLine('local_only')).toBe('This copy is on this server.');
    expect(verificationLine('unverified')).toBe('Could not be verified with Backboard just now.');
  });
});


describe('backend safeguards retained with main card', () => {
  it('never presents generic other as relevant even if a response contains rows', () => {
    expect(relevantView(body({memories: [m('remote_verified')]}), false, 'other')).toEqual({kind: 'empty'});
  });
  it('does not hide provider failures behind an empty generic category', () => {
    expect(relevantView(body({memories: [m('unverified')]}), true, 'other')).toEqual({kind: 'error'});
    expect(relevantView(body({retrieval_mode: 'unavailable', memories: [m('unverified')]}), false, 'other')).toEqual({kind: 'unavailable'});
  });
});
