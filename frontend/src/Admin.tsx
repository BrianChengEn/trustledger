import {useEffect, useRef, useState} from 'react';
import {request, type Execution, type HistoryItem, type HistoryPage,
  type NessieQuery, type ResourceOption} from './api';

const prefix = '/admin/nessie';
const queries: [NessieQuery, string][] = [
  ['customers.list', '列出客戶'], ['accounts.list', '列出帳戶'], ['accounts.get', '查詢單一帳戶'],
  ['accounts.by_customer', '客戶的帳戶'], ['deposits.by_account', '帳戶的存款'],
  ['withdrawals.by_account', '帳戶的提款'],
];
const text = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value);

function Body({value, format, json}: {value: unknown; format: string; json: boolean}) {
  if (format === 'none') return <p>沒有可顯示的去識別化資料。</p>;
  if (json) return <pre>{JSON.stringify(value, null, 2)}</pre>;
  if (Array.isArray(value) && !value.length) return <p className="empty">查詢成功，沒有資料。</p>;
  const rows = Array.isArray(value) ? value : [value];
  if (!rows.every(row => row && typeof row === 'object' && !Array.isArray(row))) {
    return <pre>{JSON.stringify(value, null, 2)}</pre>;
  }
  const objects = rows as Record<string, unknown>[];
  const columns = [...new Set(objects.flatMap(row => Object.keys(row)))];
  return <div className="tablewrap"><table><thead><tr>{columns.map(key => <th key={key}>{key}</th>)}</tr></thead>
    <tbody>{objects.map((row, i) => <tr key={i}>{columns.map(key => <td key={key}>
      {Object.hasOwn(row, key) ? text(row[key]) : '（不存在）'}</td>)}</tr>)}</tbody></table></div>;
}

function Metadata({result}: {result: Omit<HistoryItem, 'history_id'>}) {
  return <div className="admin-meta"><b>{result.query}</b><span>來源：{result.source}</span>
    <span>UTC：{result.requested_at}</span><span>{result.duration_ms} ms</span>
    <span>Nessie HTTP status：{result.http_status ?? '未收到回應'}</span>
    {result.transport_error && <p className="error">{result.transport_error.type}</p>}
    {result.http_status !== null && (result.http_status < 200 || result.http_status >= 300) &&
      <p className="error">Nessie API 錯誤：HTTP {result.http_status}</p>}
  </div>;
}

export default function Admin() {
  const [view, setView] = useState<'query'|'history'>('query');
  const [query, setQuery] = useState<NessieQuery>('customers.list');
  const [resourceId, setResourceId] = useState('');
  const [resources, setResources] = useState<ResourceOption[]>([]);
  const [result, setResult] = useState<Execution|null>(null);
  const [queryBusy, setQueryBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState('');
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [cursor, setCursor] = useState<number|null>(null);
  const [queryJson, setQueryJson] = useState(false);
  const [deleting, setDeleting] = useState<number|'all'|null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const generation = useRef(0);
  const needsId = !['customers.list', 'accounts.list'].includes(query);
  const kind = query === 'accounts.by_customer' ? 'customer' : 'account';
  const options = resources.filter(row => row.kind === kind);

  useEffect(() => {if (deleting !== null) dialog.current?.showModal();}, [deleting]);
  useEffect(() => {void request<ResourceOption[]>(prefix+'/resources').then(setResources)
    .catch(() => setError('無法讀取本機代碼，請執行列表查詢重試。'));}, []);

  async function run() {
    if (queryBusy || (needsId && !options.some(row => row.resource_id === resourceId))) return;
    setQueryBusy(true); setError(''); setResult(null);
    try {
      setResult(await request<Execution>(prefix+'/query', {method: 'POST', body: JSON.stringify({
        query, ...(needsId ? {resource_id: resourceId} : {}),
      })}, 25000));
      setResources(await request<ResourceOption[]>(prefix+'/resources'));
    } catch (e) {setError('本機查詢失敗：'+(e instanceof Error ? e.message : '請重試。'));}
    finally {setQueryBusy(false);}
  }
  async function loadHistory(more = false) {
    const current = ++generation.current;
    setHistoryBusy(true); setError('');
    try {
      const page = await request<HistoryPage>(prefix+'/history'+(more && cursor ? '?before_id='+cursor : ''));
      if (current !== generation.current) return;
      setItems(old => more ? [...old, ...page.items.filter(row => !old.some(r => r.history_id === row.history_id))] : page.items);
      setCursor(page.next_cursor);
    } catch {if (current === generation.current) setError('無法讀取本機歷史，請重試。');}
    finally {if (current === generation.current) setHistoryBusy(false);}
  }
  function closeDialog() {dialog.current?.close(); setDeleting(null);}
  async function remove() {
    if (deleting === null || actionBusy) return;
    setActionBusy(true); setError('');
    try {
      await request(prefix+'/history'+(deleting === 'all' ? '' : '/'+deleting), {
        method: 'DELETE', body: JSON.stringify({confirm: true}),
      });
      closeDialog(); await loadHistory();
    } catch {setError('刪除失敗，請重新載入歷史確認狀態。');}
    finally {setActionBusy(false);}
  }
  return <section className="admin" lang="zh-Hant" aria-label="Nessie 開發者控制台">
    <div className="heading"><div><div className="eyebrow">Admin · Nessie</div><h1>開發者控制台</h1>
      <p>僅供本機查詢 Nessie sandbox。結果已去識別化；歷史只保存狀態與時間，不保存回應內容或提供比對。</p></div></div>
    <nav className="actions admin-tabs" aria-label="控制台分頁">
      <button id="NAV-Q" aria-current={view==='query'?'page':undefined} onClick={() => setView('query')}>查詢</button>
      <button id="NAV-H" aria-current={view==='history'?'page':undefined} onClick={() => {setView('history'); void loadHistory();}}>歷史</button>
    </nav>
    {error && <p className="error" role="alert">{error}</p>}
    <div id="V-QUERY" hidden={view!=='query'} className="admin-query">
      <form className="panel" onSubmit={event => {event.preventDefault(); void run();}}>
        <h2>新查詢</h2><label htmlFor="Q-FUNC">Nessie 函式</label>
        <select id="Q-FUNC" value={query} disabled={queryBusy} onChange={e => {
          setQuery(e.target.value as NessieQuery); setResourceId('');
        }}>{queries.map(([value, label]) => <option value={value} key={value}>{label} · {value}</option>)}</select>
        {needsId && <><label htmlFor="Q-ID">本機{kind==='customer'?'客戶':'帳戶'}代碼</label>
          <select id="Q-ID" value={resourceId} disabled={queryBusy} aria-describedby="Q-ID-HELP"
            onChange={e => setResourceId(e.target.value)}>
            <option value="">請選擇</option>{options.map(row => <option key={row.resource_id}
              value={row.resource_id}>{row.resource_id}</option>)}
          </select><small id="Q-ID-HELP">先執行列出客戶／帳戶以取得可選代碼。原始 ID 僅留在後端。</small></>}
        <button id="Q-RUN" className="primary" disabled={queryBusy || (needsId && !resourceId)}>執行查詢</button>
      </form>
      <section className="panel" id="Q-RESULT" aria-label="查詢結果" aria-busy={queryBusy}>
        <h2>查詢結果</h2>{queryBusy ? <p role="status">查詢中…</p> : result ? <>
          <Metadata result={result}/><p id="Q-SAVE" className={result.write_status==='failed'?'error':'badge'}>
            {result.write_status==='failed'?'failed to write':'已儲存查詢狀態 #'+result.history_id}</p>
          <div className="actions"><button id="Q-TABLE" aria-pressed={!queryJson} onClick={() => setQueryJson(false)}>表格</button>
            <button id="Q-JSON" aria-pressed={queryJson} onClick={() => setQueryJson(true)}>JSON</button></div>
          <Body value={result.response_body} format={result.body_format} json={queryJson}/>
        </> : <p className="empty">選擇函式並執行查詢。每次執行會發出新的 Nessie 請求。</p>}
      </section>
    </div>
    <section id="V-HISTORY" className="panel" hidden={view!=='history'}>
      <div className="sectiontop"><h2>查詢歷史</h2><button id="H-CLEAR" disabled={!items.length || actionBusy}
        onClick={() => setDeleting('all')}>清除全部歷史</button></div>
      {historyBusy && <p role="status">讀取歷史中…</p>}
      {!historyBusy && !items.length && <p className="empty">尚無已儲存歷史。</p>}
      {!!items.length && <div className="tablewrap"><table><thead><tr><th>查詢</th>
        <th>UTC / 來源</th><th>Nessie HTTP / 耗時</th><th>操作</th></tr></thead>
        <tbody>{items.map(row => <tr key={row.history_id}>
          <td>#{row.history_id} {row.query}</td><td>{row.requested_at}<small>{row.source}</small></td>
          <td>{row.http_status ?? row.transport_error?.type ?? '未收到回應'}<small>{row.duration_ms} ms</small></td>
          <td><button id={'H-DELETE-'+row.history_id} disabled={actionBusy} onClick={() => setDeleting(row.history_id)}>刪除</button></td>
        </tr>)}</tbody></table></div>}
      {cursor && <button id="H-MORE" disabled={historyBusy} onClick={() => void loadHistory(true)}>載入更多</button>}
    </section>
    <dialog id="D-CONFIRMATION" ref={dialog} aria-labelledby="D-TITLE" onCancel={event => {
      event.preventDefault(); if (!actionBusy) closeDialog();
    }}><h2 id="D-TITLE">確定刪除{deleting==='all'?'全部本機歷史':'歷史 #'+deleting}？</h2>
      <p>此操作無法復原，只刪除本機查詢狀態。Nessie 資料、代碼與匯入進度會保留。</p>
      <div className="actions"><button id="D-CANCEL" autoFocus disabled={actionBusy} onClick={closeDialog}>取消</button>
        <button id="D-CONFIRM" disabled={actionBusy} onClick={() => void remove()}>確認刪除</button></div>
      {error && <p role="alert" className="error">{error}</p>}
    </dialog>
  </section>;
}
