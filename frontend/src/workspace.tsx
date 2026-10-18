import {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {request, ApiError, type Alert, type Analysis, type Confirmation, type Health, type Memory, type Transaction} from './api';

/** One explicit AI request. Nothing is ever started automatically. */
export type Run =
  | {state: 'running'}
  | {state: 'done'; result: Analysis; at: number; memoryKey: string}
  | {state: 'failed'; message: string};

export interface Workspace {
  loaded: boolean; loading: boolean; error: string;
  health: Health | null; transactions: Transaction[]; alerts: Alert[]; memories: Memory[];
  runs: Record<string, Run>; outcomes: Record<string, Confirmation>;
  memoryKey: string; busy: boolean; notice: string;
  refresh: () => Promise<void>;
  analyze: (transactionId: string) => Promise<void>;
  confirm: (alert: Alert, decision: 'normal' | 'review', consent: boolean) => Promise<Confirmation | null>;
  forget: (memoryId: string) => Promise<boolean>;
  dismissNotice: () => void;
}

const Ctx = createContext<Workspace | null>(null);
export const useWorkspace = () => {
  const value = useContext(Ctx);
  if (!value) throw new Error('useWorkspace outside provider');
  return value;
};

const friendly: Record<string, string> = {
  memory_delete_failed: 'Backboard could not delete this memory, so it was kept. Nothing was removed locally either. Try again.',
  confirmation_conflict: 'This alert already has a different decision recorded.',
  not_found: 'That item no longer exists. Refresh and try again.',
};
export const explain = (e: unknown, fallback: string) =>
  e instanceof ApiError && e.code && friendly[e.code] ? friendly[e.code] : fallback;

export function WorkspaceProvider({children}: {children: ReactNode}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<Record<string, Run>>({});
  const [outcomes, setOutcomes] = useState<Record<string, Confirmation>>({});
  const memoryKey = useMemo(() => memories.map(m => m.memory_id).sort().join(','), [memories]);
  const memoryKeyRef = useRef(memoryKey);
  memoryKeyRef.current = memoryKey;

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [h, t, a, m] = await Promise.all([
        request<Health>('/health'), request<Transaction[]>('/transactions'),
        request<Alert[]>('/alerts'), request<Memory[]>('/memories'),
      ]);
      setHealth(h); setTransactions(t); setAlerts(a); setMemories(m); setLoaded(true);
    } catch { setError('Cannot reach the TrustLedger API. Start the backend on port 8000, then retry.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const analyze = useCallback(async (transactionId: string) => {
    setRuns(r => ({...r, [transactionId]: {state: 'running'}}));
    try {
      // The only call that may reach an AI provider. A real Jev round trip can take several seconds.
      const result = await request<Analysis>('/analyses', {method: 'POST', body: JSON.stringify({transaction_id: transactionId})}, 60000);
      setRuns(r => ({...r, [transactionId]: {state: 'done', result, at: Date.now(), memoryKey: memoryKeyRef.current}}));
    } catch (e) {
      const timedOut = e instanceof DOMException && e.name === 'TimeoutError';
      setRuns(r => ({...r, [transactionId]: {state: 'failed', message: timedOut
        ? 'The analysis request timed out. The rules result above is unaffected.'
        : 'The analysis request failed. The rules result above is unaffected.'}}));
    }
  }, []);

  const confirm = useCallback(async (alert: Alert, decision: 'normal' | 'review', consent: boolean) => {
    setBusy(true); setNotice('');
    try {
      const result = await request<Confirmation>(`/alerts/${encodeURIComponent(alert.alert_id)}/confirmations`,
        {method: 'POST', body: JSON.stringify({decision, consent_to_memory: consent})});
      setOutcomes(o => ({...o, [alert.transaction_id]: result}));
      await refresh();
      return result;
    } catch (e) {
      setError(explain(e, 'The confirmation could not be saved. Nothing was recorded; please retry.'));
      return null;
    } finally { setBusy(false); }
  }, [refresh]);

  const forget = useCallback(async (memoryId: string) => {
    setBusy(true); setNotice('');
    try {
      await request<void>('/memories/' + encodeURIComponent(memoryId), {method: 'DELETE'});
      await refresh();
      setNotice('Memory deleted. Future analyses will no longer use it.');
      return true;
    } catch (e) {
      setError(explain(e, 'Could not delete the memory. Please retry.'));
      return false;
    } finally { setBusy(false); }
  }, [refresh]);

  const value: Workspace = {loaded, loading, error, health, transactions, alerts, memories, runs, outcomes,
    memoryKey, busy, notice, refresh, analyze, confirm, forget, dismissNotice: () => { setNotice(''); setError(''); }};
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
