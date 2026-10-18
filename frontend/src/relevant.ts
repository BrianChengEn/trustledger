import {useEffect, useRef, useState} from 'react';
import {request, type RelevantMemories, type RelevantMemory} from './api';
import {useWorkspace} from './workspace';

/** What the card is allowed to show. An empty list is never a match, and an error never keeps an old sentence. */
export type RelevantView =
  | {kind: 'loading'} | {kind: 'error'} | {kind: 'unavailable'} | {kind: 'empty'}
  | {kind: 'found'; memories: RelevantMemory[]};

export function relevantView(result: RelevantMemories | null, failed: boolean, category?: string): RelevantView {
  if (failed) return {kind: 'error'};
  if (!result) return {kind: 'loading'};
  if (result.retrieval_mode === 'unavailable') return {kind: 'unavailable'};
  // retrieval_mode can say remote_verified with an empty list: that is "nothing found", not a match.
  if (category === 'other' || !result.memories.length) return {kind: 'empty'};
  return {kind: 'found', memories: result.memories};
}

/** One line per memory, from its own verification state. Never says Backboard checked a copy it did not check. */
export const verificationLine = (v: RelevantMemory['verification']) =>
  v === 'remote_verified' ? 'Checked with Backboard just now.'
    : v === 'local_only' ? 'This copy is on this server.'
    : 'Could not be verified with Backboard just now.';

/** Reads GET /transactions/{id}/relevant-memories. Read-only; reloads when memories or the workspace change. */
export function useRelevantMemories(transactionId: string | undefined, enabled = true, category?: string) {
  const {prefix, revision, ready, memoryKey} = useWorkspace();
  const [state, setState] = useState<{key: string; result?: RelevantMemories; failed?: boolean} | null>(null);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef<{key: string; promise: Promise<RelevantMemories>} | null>(null);
  const key = [prefix, transactionId, category, memoryKey, revision, attempt, ready, enabled].join('|');
  useEffect(() => {
    if (!transactionId || !ready || !enabled) { inFlight.current = null; setState(null); return; }
    let active = true;
    // Reuse an identical in-flight read during StrictMode's effect replay.
    const promise = inFlight.current?.key === key ? inFlight.current.promise
      : request<RelevantMemories>(prefix + '/transactions/' + encodeURIComponent(transactionId) + '/relevant-memories', undefined, 15000);
    inFlight.current = {key, promise};
    promise.then(result => { if (active) setState({key, result}); })
      .catch(() => { if (active) setState({key, failed: true}); })
      .finally(() => { if (inFlight.current?.promise === promise) inFlight.current = null; });
    return () => { active = false; };
  }, [transactionId, key, prefix, ready, enabled]);
  const current = ready && enabled && state?.key === key ? state : null;
  const view: RelevantView = !ready ? {kind: 'unavailable'} : relevantView(current?.result ?? null, !!current?.failed, category);
  return {view,
    result: current?.result ?? null, retry: () => { setState(null); setAttempt(n => n + 1); }};
}
