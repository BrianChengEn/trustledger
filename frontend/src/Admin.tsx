import {useEffect, useRef, useState} from 'react';
import {request, type Comparison, type Execution, type HistoryItem, type HistoryPage,
  type NessieQuery} from './api';

const prefix = '/admin/nessie';
const queries: [NessieQuery, string][] = [
  ['customers.list', '列出客戶'], ['accounts.list', '列出帳戶'], ['accounts.get', '查詢單一帳戶'],
  ['accounts.by_customer', '客戶的帳戶'], ['deposits.by_account', '帳戶的存款'],
  ['withdrawals.by_account', '帳戶的提款'],
];
const text = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value);
const compatible = (left?: HistoryItem, right?: HistoryItem) => !!left && !!right &&
  left.history_id !== right.history_id && left.query === right.query &&
  left.resource_id === right.resource_id && left.source === right.source;

function Body({value, format, json}: {value: unknown; format: string; json: boolean}) {
  if (format === 'none') return <p>未收到 HTTP 回應，沒有回應內容。</p>;
  if (json || format === 'text') return <pre>{format === 'text' ? text(value) : JSON.stringify(value, null, 2)}</pre>;
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
    {result.resource_id && <span>ID：{result.resource_id}</span>}
    {result.transport_error && <p className="error">{result.transport_error.type}：{result.transport_error.message}</p>}
    {result.http_status !== null && (result.http_status < 200 || result.http_status >= 300) &&
      <p className="error">Nessie API 錯誤：HTTP {result.http_status}</p>}
  </div>;
}

function Toggles({id, json, onChange}: {id: string; json: boolean; onChange: (v: boolean) => void}) {
  return <div className="actions"><button id={id+'-TABLE'} aria-pressed={!json} onClick={() => onChange(false)}>表格</button>
    <button id={id+'-JSON'} aria-pressed={json} onClick={() => onChange(true)}>JSON</button></div>;
}

export default function Admin() {
  const [view, setView] = useState<'query'|'history'|'compare'>('query');
  const [query, setQuery] = useState<NessieQuery>('customers.list');
  const [resourceId, setResourceId] = useState('');
  const [result, setResult] = useState<Execution|null>(null);
  const [queryBusy, setQueryBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState('');
  const [queryError, setQueryError] = useState('');
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [cursor, setCursor] = useState<number|null>(null);
  const [detail, setDetail] = useState<Execution|null>(null);
  const [left, setLeft] = useState<HistoryItem|null>(null);
  const [right, setRight] = useState<HistoryItem|null>(null);
  const [comparison, setComparison] = useState<Comparison|null>(null);
  const [queryJson, setQueryJson] = useState(false);
  const [historyJson, setHistoryJson] = useState(false);
  const [compareJson, setCompareJson] = useState(false);
  const [deleting, setDeleting] = useState<number|'all'|null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const needsId = !['customers.list', 'accounts.list'].includes(query);
  const leftId = left?.history_id ?? null;
  const rightId = right?.history_id ?? null;
  const canCompare = compatible(left ?? undefined, right ?? undefined);

  useEffect(() => {if (deleting !== null) dialog.current?.showModal();}, [deleting]);

  async function run() {
    if (queryBusy) return;
    const id = resourceId.trim().toLowerCase();
    if (needsId && !/^(?:[0-9a-f]{24}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/.test(id)) {
      setQueryError('請輸入 24 位十六進位 ID 或標準 UUID。'); return;
    }
    setQueryBusy(true); setQueryError(''); setResult(null);
    try {
      setResult(await request<Execution>(prefix+'/query', {method: 'POST', body: JSON.stringify({
        query, ...(needsId ? {resource_id: id} : {}),
      })}, 25000));
    } catch (e) {setQueryError('本機查詢失敗：'+(e instanceof Error ? e.message : '請重試。'));}
    finally {setQueryBusy(false);}
  }
  async function loadHistory(more = false) {
    setHistoryBusy(true); setError('');
    try {
      const page = await request<HistoryPage>(prefix+'/history'+(more && cursor ? '?before_id='+cursor : ''));
      setItems(old => more ? [...old, ...page.items.filter(row => !old.some(r => r.history_id === row.history_id))] : page.items);
      setCursor(page.next_cursor);
    } catch {setError('無法讀取本機歷史，請重新開啟歷史分頁重試。');}
    finally {setHistoryBusy(false);}
  }
  function openHistory() {setView('history'); void loadHistory();}
  async function inspect(id: number) {
    setActionBusy(true); setError(''); setDetail(null);
    try {setDetail(await request<Execution>(prefix+'/history/'+id));}
    catch (e) {
      if (e instanceof Error && e.message.includes('history_not_found')) {
        await recoverMissing();
      } else setError('無法讀取已儲存回應，請重試。');
    } finally {setActionBusy(false);}
  }
  async function recoverMissing() {
    setLeft(null); setRight(null); setComparison(null); setDetail(null); setView('history');
    await loadHistory(); setError('選取的歷史已刪除，請重新選擇。');
  }
  async function compare() {
    if (!canCompare || actionBusy) return;
    setView('compare'); setActionBusy(true); setError(''); setComparison(null);
    try {setComparison(await request<Comparison>(prefix+'/compare', {method: 'POST',
      body: JSON.stringify({left_id: leftId, right_id: rightId})}));}
    catch (e) {
      if (e instanceof Error && e.message.includes('history_not_found')) await recoverMissing();
      else setError('無法比較，請確認兩筆歷史相容且集合含唯一 _id，再重試。');
    } finally {setActionBusy(false);}
  }
  function closeDialog() {dialog.current?.close(); setDeleting(null);}
  async function remove() {
    if (deleting === null || actionBusy) return;
    setActionBusy(true); setError('');
    try {
      await request(prefix+'/history'+(deleting === 'all' ? '' : '/'+deleting), {
        method: 'DELETE', body: JSON.stringify({confirm: true}),
      });
      if (deleting === 'all' || detail?.history_id === deleting) setDetail(null);
      if (deleting === 'all' || leftId === deleting || rightId === deleting) {
        setLeft(null); setRight(null); setComparison(null);
      }
      closeDialog(); await loadHistory();
    } catch (e) {
      if (e instanceof Error && e.message.includes('history_not_found')) {
        closeDialog(); await recoverMissing();
      } else setError('刪除失敗，歷史仍保留。請重試。');
    } finally {setActionBusy(false);}
  }
  return <section className="admin" lang="zh-Hant" aria-label="Nessie 開發者控制台">
    <div className="heading"><div><div className="eyebrow">Admin · Nessie</div><h1>開發者控制台</h1>
      <p>僅供本機單一開發者查詢 Nessie sandbox。歷史快照不會傳送至 AI 或確認記憶。</p></div></div>
    <nav className="actions admin-tabs" aria-label="控制台分頁">
      <button id="NAV-Q" aria-current={view==='query'?'page':undefined} onClick={() => setView('query')}>查詢</button>
      <button id="NAV-H" aria-current={view==='history'?'page':undefined} onClick={openHistory}>歷史</button>
      <button id="NAV-C" aria-current={view==='compare'?'page':undefined} onClick={() => setView('compare')}>比較</button>
    </nav>
    {error && <p className="error" role="alert">{error}</p>}
    <div id="V-QUERY" hidden={view!=='query'} className="admin-query">
      <form className="panel" onSubmit={event => {event.preventDefault(); void run();}}>
        <h2>新查詢</h2><label htmlFor="Q-FUNC">Nessie 函式</label>
        <select id="Q-FUNC" value={query} disabled={queryBusy} onChange={e => {
          setQuery(e.target.value as NessieQuery); setQueryError('');
        }}>{queries.map(([value, label]) => <option value={value} key={value}>{label} · {value}</option>)}</select>
        {needsId && <><label htmlFor="Q-ID">{query==='accounts.by_customer'?'Customer':'Account'} ID</label>
          <input id="Q-ID" value={resourceId} disabled={queryBusy} maxLength={128}
            aria-describedby="Q-ID-HELP" onChange={e => setResourceId(e.target.value)}/>
          <small id="Q-ID-HELP">24 位十六進位或標準 UUID；由 Nessie 指派。</small></>}
        <button id="Q-RUN" className="primary" disabled={queryBusy}>執行查詢</button>
        {queryError && <p className="error" role="alert">{queryError}</p>}
      </form>
      <section className="panel" id="Q-RESULT" aria-label="查詢結果" aria-busy={queryBusy}>
        <h2>查詢結果</h2>{queryBusy ? <p role="status">查詢中…</p> : result ? <>
          <Metadata result={result}/><p id="Q-SAVE" className={result.write_status==='failed'?'error':'badge'}>
            {result.write_status==='failed'?'failed to write':'已儲存歷史 #'+result.history_id}</p>
          <Toggles id="Q" json={queryJson} onChange={setQueryJson}/>
          <Body value={result.response_body} format={result.body_format} json={queryJson}/>
        </> : <p className="empty">選擇函式並執行查詢。每次執行會發出新的 Nessie 請求。</p>}
      </section>
    </div>
    <section id="V-HISTORY" className="panel" hidden={view!=='history'}>
      <div className="sectiontop"><h2>查詢歷史</h2><button id="H-CLEAR" disabled={!items.length || actionBusy}
        onClick={() => setDeleting('all')}>清除全部歷史</button></div>
      {historyBusy && <p role="status">讀取歷史中…</p>}
      {!historyBusy && !items.length && <p className="empty">尚無已儲存歷史。</p>}
      {!!items.length && <div className="tablewrap"><table><thead><tr><th>左</th><th>右</th><th>查詢 / ID</th>
        <th>原始 UTC / 來源</th><th>Nessie HTTP / 耗時</th><th>操作</th></tr></thead>
        <tbody>{items.map(row => <tr key={row.history_id}>
          <td><input id={'H-L-'+row.history_id} type="radio" name="left" aria-label={'左側歷史 '+row.history_id}
            checked={leftId===row.history_id} onChange={() => setLeft(row)}/></td>
          <td><input id={'H-R-'+row.history_id} type="radio" name="right" aria-label={'右側歷史 '+row.history_id}
            checked={rightId===row.history_id} onChange={() => setRight(row)}/></td>
          <td>#{row.history_id} {row.query}<small>{row.resource_id || '全部'}</small></td>
          <td>{row.requested_at}<small>{row.source}</small></td>
          <td>{row.http_status ?? row.transport_error?.type ?? '未收到回應'}<small>{row.duration_ms} ms</small></td>
          <td><button id={'H-VIEW-'+row.history_id} disabled={actionBusy} onClick={() => void inspect(row.history_id)}>檢視</button>{' '}
            <button id={'H-DELETE-'+row.history_id} disabled={actionBusy} onClick={() => setDeleting(row.history_id)}>刪除</button></td>
        </tr>)}</tbody></table></div>}
      <div className="actions"><button id="H-COMPARE" disabled={!canCompare || actionBusy}
        onClick={() => void compare()}>比較選取快照</button>
        {cursor && <button id="H-MORE" disabled={historyBusy} onClick={() => void loadHistory(true)}>載入更多</button>}</div>
      {(leftId || rightId) && <p>左側：{leftId ? '#'+leftId : '未選擇'}；右側：{rightId ? '#'+rightId : '未選擇'}</p>}
      {!canCompare && <p>請選擇兩筆不同且 query、resource_id、source 相同的歷史。</p>}
      {actionBusy && <p role="status">處理中…</p>}
      {detail && <section id="H-DETAIL" aria-label="已儲存回應"><h3>已儲存快照 #{detail.history_id}</h3>
        <Metadata result={detail}/><Toggles id="H" json={historyJson} onChange={setHistoryJson}/>
        <Body value={detail.response_body} format={detail.body_format} json={historyJson}/></section>}
    </section>
    <section id="V-COMPARE" className="panel" hidden={view!=='compare'}>
      <div className="sectiontop"><h2>快照比較</h2><button id="C-BACK" onClick={() => setView('history')}>返回歷史</button></div>
      {actionBusy ? <p role="status">比較中…</p> : comparison ? <>
        <Toggles id="C" json={compareJson} onChange={setCompareJson}/>
        <div className="admin-snapshots">{(['left','right'] as const).map(side => <section id={side==='left'?'C-LEFT':'C-RIGHT'} key={side}>
          <h3>{side==='left'?'左側':'右側'} #{comparison[side].history_id}</h3><Metadata result={comparison[side]}/>
          <Body value={comparison[side].response_body} format={comparison[side].body_format} json={compareJson}/>
        </section>)}</div><section id="C-DIFF"><h3>{comparison.comparison.data_changed?'有差異':'資料未變更'}</h3>
          {comparison.comparison.status_change && <p>HTTP 狀態：{comparison.comparison.status_change.before ?? '無回應'} → {comparison.comparison.status_change.after ?? '無回應'}</p>}
          {comparison.comparison.transport_change && <pre>{JSON.stringify(comparison.comparison.transport_change, null, 2)}</pre>}
          {comparison.comparison.changes.map((change, i) => <article className={'admin-change '+change.kind} key={i}>
            <b>{({added:'新增', removed:'刪除', changed:'修改'})[change.kind]} · {change.record_id} {change.path || '/'}</b>
            <p>之前：{change.before_present ? text(change.before) : '（不存在）'}</p>
            <p>之後：{change.after_present ? text(change.after) : '（不存在）'}</p>
          </article>)}</section>
      </> : <p className="empty">請至歷史分頁選擇兩筆相容快照。</p>}
    </section>
    <dialog id="D-CONFIRMATION" ref={dialog} aria-labelledby="D-TITLE" onCancel={event => {
      event.preventDefault(); if (!actionBusy) closeDialog();
    }}><h2 id="D-TITLE">確定刪除{deleting==='all'?'全部本機歷史':'歷史 #'+deleting}？</h2>
      <p>此操作無法復原，只刪除本機歷史。Nessie 資料與匯入進度會保留。</p>
      <div className="actions"><button id="D-CANCEL" autoFocus disabled={actionBusy} onClick={closeDialog}>取消</button>
        <button id="D-CONFIRM" disabled={actionBusy} onClick={() => void remove()}>確認刪除</button></div>
      {error && <p role="alert" className="error">{error}</p>}
    </dialog>
  </section>;
}
