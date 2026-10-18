import {useCallback, useEffect, useRef, useState} from 'react';
import {request, type DataSource, type SourcePage} from './api';
import Pager from './Pager';
import {href} from './route';
import {Chip} from './ui';

const LIMIT = 25;

export default function SourceLedger() {
  const [source, setSource] = useState<DataSource>('nessie');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<SourcePage|null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const load = useCallback(async (selected: DataSource, start: number, refresh = false) => {
    const current = ++generation.current;
    setBusy(true); setError(''); setPage(null);
    try {
      const result = await request<SourcePage>('/data-sources/' + selected + (refresh ? '/refresh'
        : '/transactions?limit=' + LIMIT + '&offset=' + start), refresh ? {method: 'POST', body: '{}'} : undefined);
      if (current === generation.current) {
        setPage(result);
        if (refresh) setOffset(0);
      }
    } catch (e) {
      if (current === generation.current) setError(e instanceof Error ? e.message : 'Source unavailable.');
    } finally {if (current === generation.current) setBusy(false);}
  }, []);
  useEffect(() => {
    void load(source, offset);
    return () => {generation.current++;};
  }, [source, offset, load]);
  function select(next: DataSource) {
    generation.current++; setPage(null); setOffset(0); setSource(next);
  }
  function move(next: number) {generation.current++; setPage(null); setOffset(next);}
  return <section id="V-SOURCES" className="panel fill" lang="en" aria-label="Source transactions" aria-busy={busy}>
    <div className="sectiontop"><div className="actions" role="group" aria-label="Transaction data source">
      {(['nessie', 'banksim'] as const).map(value => <button key={value} id={'S-' + value.toUpperCase()}
        aria-pressed={source === value} disabled={source === value} onClick={() => select(value)}>
        {value === 'nessie' ? 'Nessie' : 'BankSim'}</button>)}
    </div>{source === 'nessie' && <button id="S-REFRESH" disabled={busy}
      onClick={() => void load('nessie', 0, true)}>Refresh Nessie</button>}</div>
    <p>{source === 'banksim' ? 'BankSim research data · EUR · simulation days. Labels and model results are not shown.'
      : 'Nessie sandbox · cached normalized transactions. Refresh explicitly to fetch the sandbox.'}</p>
    {busy && <p role="status">Loading source transactions…</p>}
    {error && <p className="error" role="alert">{error}{' '}<button onClick={() => void load(source, offset)}>Retry</button></p>}
    {page && <>
      <div className="admin-meta"><b>{page.total.toLocaleString()} transactions</b>
        <Chip tone={page.data_mode === 'degraded' ? 'warn' : 'neutral'}>{page.data_mode}</Chip>
        {page.last_synced_at && <span>Last collection success: {page.last_synced_at}</span>}</div>
      {page.data_mode === 'degraded' && <p role="status">Refresh was incomplete. These are cached records.</p>}
      {page.items.length ? <div className="paged" key={source + offset}>
        <div className="tablewrap"><table><thead><tr><th>Merchant / category</th><th>When</th><th>Amount</th></tr></thead>
          <tbody>{page.items.map(row => <tr key={row.id}>
            <td>{row.merchant_display ?? (row.merchant_code ? 'Merchant code ' + row.merchant_code : 'Unknown merchant')}
              <small>{row.source_category ?? row.merchant_category ?? 'Unknown category'} · {row.kind}</small></td>
            <td>{row.simulation_step !== null ? 'Simulation day ' + row.simulation_step
              : row.occurred_date ?? row.occurred_at ?? 'Unknown date'}
              <small>{row.occurred_date ? 'Date only' : row.simulation_step !== null ? 'No clock time' : ''}</small></td>
            <td>{row.currency ? new Intl.NumberFormat('en-US', {style: 'currency', currency: row.currency}).format(row.amount_minor / 100)
              : (row.amount_minor / 100).toFixed(2) + ' · currency unknown'}</td>
          </tr>)}</tbody></table></div><Pager/></div> : <p className="empty">No imported transactions for this source.</p>}
      <div className="actions"><button id="S-PREV" disabled={busy || !offset} onClick={() => move(Math.max(0, offset - LIMIT))}>Previous records</button>
        <span>{page.total ? offset + 1 : 0}–{offset + page.items.length} of {page.total.toLocaleString()}</span>
        <button id="S-NEXT" disabled={busy || page.next_offset === null} onClick={() => move(page.next_offset!)}>Next records</button></div>
      {page.customer_code && <a href={href({view: 'today', customer: page.customer_code})}>Review current Nessie transactions</a>}
    </>}
  </section>;
}
