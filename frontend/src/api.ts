export type Role = 'user'|'admin';
export interface Session {
  authenticated: boolean; role: Role|null; login_required: boolean;
  admin_available: boolean; demo_edit_enabled: boolean;
}
export const UNAUTHORIZED_EVENT = 'trustledger:unauthorized';
export interface Transaction {
  id: string; occurred_at: string; amount: number; currency: 'USD'; direction: 'debit'|'credit'|'unknown';
  merchant_display: string; merchant_category: string; source: 'synthetic'|'nessie';
  account_token: string; is_subscription: boolean;
  kind?: 'purchase'|'transfer'|'deposit'|'withdrawal';
}
export interface Analysis {
  transaction_id: string; alert_type: 'duplicate'|'amount_anomaly'|'subscription_change'|'none';
  severity: 'low'|'medium'|'high'; needs_human: boolean; confidence: number;
  evidence: string[]; provider_mode: string; model_version: string|null; request_id: string;
}
export interface Alert extends Analysis {alert_id: string; status: 'open'|'normal'|'review'}
export function inspectionStatus(alert?: Alert): 'normal'|'needreviews'|'pending' {
  if (!alert || alert.status==='normal') return 'normal';
  return alert.status==='open' ? 'pending' : 'needreviews';
}
export interface Movement extends Transaction {
  kind: 'purchase'|'transfer'|'deposit'|'withdrawal';
  settlement_status: 'pending'|'completed'|'cancelled'; date_only: boolean;
}
export interface WorkspaceSnapshot {
  customer_id: string|null; data_mode: string;
  accounts: {account_token: string; type: string; balance: number; rewards: number}[];
  transactions: Movement[];
  sync: {account_token: string; kind: string; requested_at: string; synced_at: string|null;
    http_status: number|null; error: string|null}[];
}
export interface PrivacyPreview {
  transaction_id: string; destination: string; schema_version: string;
  inspection: {field: string; action: string; output: string|null; reason: string}[];
  safe_payload: Record<string, string|number|boolean>;
}
export interface Memory {memory_id: string; summary: string; source: string; created_at: string}
export interface Health {status: string; data_mode: string; analysis_mode: string; memory_mode: string}
export interface Confirmation {decision: string; memory_status: string; memory_id: string|null}
const base = import.meta.env.VITE_API_BASE_URL || '';
/** Error carrying only the backend's safe error code (never an upstream body). */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string|null) {super(message);}
}
export async function request<T>(path: string, options?: RequestInit, timeoutMs = 180000): Promise<T> {
  const response = await fetch(base + '/api/v1' + path, {
    ...options, headers: {'Content-Type': 'application/json', ...options?.headers},
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const code: string|null = typeof body?.error?.code === 'string' ? body.error.code : null;
    if (response.status === 401 && code === 'auth_required') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(code ? `Request failed: ${code}` : `API returned ${response.status}`, response.status, code);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const labels: Record<Analysis['alert_type'], string> = {
  duplicate: 'Possible duplicate', amount_anomaly: 'Unusual amount',
  subscription_change: 'Subscription increased', none: 'No rule triggered',
};
export const money = (amount: number) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(amount);

export type NessieQuery = 'customers.list'|'accounts.list'|'accounts.get'|'accounts.by_customer'|
  'deposits.by_account'|'withdrawals.by_account'|'purchases.by_account'|'transfers.by_account';
export interface ResourceOption {resource_id: string; kind: 'customer'|'account'}
export interface HistoryItem {
  history_id: number; source: 'nessie'|'synthetic'; query: NessieQuery;
  requested_at: string; duration_ms: number; http_status: number|null;
  transport_error: {type: string; message: string}|null;
}
export interface Execution extends Omit<HistoryItem, 'history_id'> {
  history_id: number|null; response_body: unknown; body_format: 'json'|'none';
  write_status: 'saved'|'failed'; write_label: string|null;
}
export interface HistoryPage {items: HistoryItem[]; next_cursor: number|null}
