import {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {request, ApiError, type Alert, type Analysis, type Confirmation, type Health, type Memory, type Movement, type WorkspaceSnapshot} from './api';
import {go as navigate, href as routeHref, type Route} from './route';

export type Run =
  | {state: 'running'}
  | {state: 'done'; result: Analysis; at: number; memoryKey: string}
  | {state: 'failed'; message: string};

export interface Workspace {
  loaded: boolean; loading: boolean; ready: boolean; error: string; revision: number; prefix: string;
  snapshot: WorkspaceSnapshot | null;
  health: Health | null; transactions: Movement[]; alerts: Alert[]; memories: Memory[];
  runs: Record<string, Run>; outcomes: Record<string, Confirmation>;
  memoryKey: string; busy: boolean; notice: string;
  refresh: () => Promise<boolean>;
  analyze: (transactionId: string) => Promise<void>;
  confirm: (alert: Alert, decision: 'normal' | 'review', consent: boolean) => Promise<Confirmation | null>;
  forget: (memoryId: string) => Promise<boolean>;
  go: (route: Route) => void; href: (route: Route) => string;
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

export function WorkspaceProvider({children, customerId, active = true}: {
  children: ReactNode; customerId?: string; active?: boolean;
}) {
  const prefix = customerId ? '/admin/nessie/customers/' + encodeURIComponent(customerId) : '';
  const generation = useRef(0);
  const mounted = useRef(false);
  const readyRef = useRef(false);
  const pending = useRef(new Set<string>());
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [transactions, setTransactions] = useState<Movement[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<Record<string, Run>>({});
  const [outcomes, setOutcomes] = useState<Record<string, Confirmation>>({});
  const memoryKey = useMemo(() => memories.map(m => m.memory_id).sort().join(','), [memories]);
  const memoryKeyRef = useRef(memoryKey);
  memoryKeyRef.current = memoryKey;

  const refresh = useCallback(async () => {
    if (!mounted.current || pending.current.has('mutation')) return false;
    const current = ++generation.current;
    readyRef.current = false;
    setReady(false); setRevision(current);
    setRuns(rows => Object.fromEntries(Object.entries(rows).filter(([, run]) => run.state === 'done')));
    setLoading(true); setError('');
    try {
      const view = await request<WorkspaceSnapshot>(prefix + '/workspace/refresh', {method: 'POST', body: '{}'});
      if (current !== generation.current) return false;
      setSnapshot(view); setTransactions(view.transactions); setLoaded(true);
      const [h, a, m] = await Promise.all([
        request<Health>(prefix + '/health'), request<Alert[]>(prefix + '/alerts'), request<Memory[]>(prefix + '/memories'),
      ]);
      if (current !== generation.current) return false;
      setHealth(h); setAlerts(a); setMemories(m); setReady(true); readyRef.current = true;
      return true;
    } catch (e) {
      if (current === generation.current) setError(explain(e,
        'Operation stopped. The workspace could not refresh; last displayed data may be cached. Retry before taking action.'));
      return false;
    } finally { if (current === generation.current) setLoading(false); }
  }, [prefix]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current++; };
  }, []);
  useEffect(() => {
    if (active) void refresh();
    return () => { generation.current++; readyRef.current = false; };
  }, [refresh, active]);

  const analyze = async (transactionId: string) => {
    const operation = 'analysis:' + transactionId;
    if (!readyRef.current || pending.current.has(operation)) return;
    pending.current.add(operation);
    const current = generation.current;
    const requestedMemory = memoryKeyRef.current;
    setRuns(r => ({...r, [transactionId]: {state: 'running'}}));
    try {
      const result = await request<Analysis>(prefix + '/analyses', {method: 'POST', body: JSON.stringify({transaction_id: transactionId})});
      if (current === generation.current) setRuns(r => ({...r, [transactionId]: {
        state: 'done', result, at: Date.now(), memoryKey: requestedMemory,
      }}));
    } catch (e) {
      if (current === generation.current) setRuns(r => ({...r, [transactionId]: {state: 'failed', message:
        e instanceof DOMException && e.name === 'TimeoutError'
          ? 'The analysis request timed out. Refresh before retrying; the rules remain authoritative.'
          : 'The analysis request failed. Refresh before retrying; the rules remain authoritative.'}}));
    } finally { pending.current.delete(operation); }
  };

  const confirm = async (alert: Alert, decision: 'normal' | 'review', consent: boolean) => {
    if (!readyRef.current || pending.current.has('mutation')) return null;
    pending.current.add('mutation');
    setBusy(true); setNotice('');
    try {
      const result = await request<Confirmation>(prefix + '/alerts/' + encodeURIComponent(alert.alert_id) + '/confirmations',
        {method: 'POST', body: JSON.stringify({decision, consent_to_memory: consent})});
      if (!mounted.current) return result;
      setOutcomes(o => ({...o, [alert.transaction_id]: result}));
      pending.current.delete('mutation');
      if (!await refresh()) setNotice('Your decision was recorded. Refresh to load its current state.');
      return result;
    } catch (e) {
      if (mounted.current) {
        readyRef.current = false; setReady(false);
        setError(explain(e, 'The confirmation could not be completed. Refresh to check its state before retrying.'));
      }
      return null;
    } finally { pending.current.delete('mutation'); if (mounted.current) setBusy(false); }
  };

  const forget = async (memoryId: string) => {
    if (!readyRef.current || pending.current.has('mutation')) return false;
    pending.current.add('mutation');
    setBusy(true); setNotice('');
    try {
      await request<void>(prefix + '/memories/' + encodeURIComponent(memoryId), {method: 'DELETE'});
      if (!mounted.current) return true;
      setMemories(rows => rows.filter(row => row.memory_id !== memoryId));
      pending.current.delete('mutation');
      const refreshed = await refresh();
      setNotice(refreshed ? 'Memory deleted. Future analyses will no longer use it.' : 'Memory deleted. Refresh to load the current workspace.');
      return true;
    } catch (e) {
      if (mounted.current) {
        readyRef.current = false; setReady(false);
        setError(explain(e, 'Could not complete the deletion. Refresh to check its state before retrying.'));
      }
      return false;
    } finally { pending.current.delete('mutation'); if (mounted.current) setBusy(false); }
  };

  const value: Workspace = {loaded, loading, ready, revision, prefix, snapshot, error, health, transactions, alerts, memories,
    runs, outcomes, memoryKey, busy, notice, refresh, analyze, confirm, forget,
    go: route => navigate({...route, customer: customerId}), href: route => routeHref({...route, customer: customerId}),
    dismissNotice: () => { setNotice(''); setError(''); }};
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
