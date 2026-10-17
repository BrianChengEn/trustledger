export interface Transaction {
  id: string; occurred_at: string; amount: number; currency: 'USD'; direction: 'debit'|'credit';
  merchant_display: string; merchant_category: string; source: 'synthetic'|'nessie';
  account_token: string; is_subscription: boolean;
}
export interface Analysis {
  transaction_id: string; alert_type: 'duplicate'|'amount_anomaly'|'subscription_change'|'none';
  severity: 'low'|'medium'|'high'; needs_human: boolean; confidence: number;
  evidence: string[]; provider_mode: string; model_version: string|null; request_id: string;
}
export interface Alert extends Analysis {alert_id: string; status: 'open'|'normal'|'review'}
export interface PrivacyPreview {
  transaction_id: string; destination: string; schema_version: string;
  inspection: {field: string; action: string; output: string|null; reason: string}[];
  safe_payload: Record<string, string|number|boolean>;
}
export interface Memory {memory_id: string; summary: string; source: string; created_at: string}
export interface Health {status: string; data_mode: string; analysis_mode: string; memory_mode: string}
export interface Confirmation {decision: string; memory_status: string; memory_id: string|null}
const base = import.meta.env.VITE_API_BASE_URL || '';
export async function request<T>(path: string, options?: RequestInit, timeoutMs = 8000): Promise<T> {
  const response = await fetch(base + '/api/v1' + path, {
    ...options, headers: {'Content-Type': 'application/json', ...options?.headers},
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.code ? `Request failed: ${body.error.code}` : `API returned ${response.status}`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const labels: Record<Analysis['alert_type'], string> = {
  duplicate: 'Possible duplicate', amount_anomaly: 'Unusual amount',
  subscription_change: 'Subscription increased', none: 'No rule triggered',
};
export const money = (amount: number) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(amount);

export type NessieQuery = 'customers.list'|'accounts.list'|'accounts.get'|'accounts.by_customer'|
  'deposits.by_account'|'withdrawals.by_account';
export interface HistoryItem {
  history_id: number; source: 'nessie'|'synthetic'; query: NessieQuery; resource_id: string|null;
  requested_at: string; duration_ms: number; http_status: number|null;
  body_format: 'json'|'text'|'none'; transport_error: {type: string; message: string}|null;
}
export interface Execution extends Omit<HistoryItem, 'history_id'> {
  history_id: number|null; response_body: unknown; write_status: 'saved'|'failed'; write_label: string|null;
}
export interface HistoryPage {items: HistoryItem[]; next_cursor: number|null}
export interface SnapshotChange {
  kind: 'added'|'removed'|'changed'; record_id?: string|null; path: string;
  before_present: boolean; after_present: boolean; before: unknown; after: unknown;
}
export interface Comparison {
  left: Execution; right: Execution; comparison: {
    data_changed: boolean; changes: SnapshotChange[];
    status_change: {before: number|null; after: number|null}|null;
    transport_change: {before: unknown; after: unknown}|null;
  };
}
