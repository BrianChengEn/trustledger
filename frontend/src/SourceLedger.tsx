import {useCallback, useEffect, useRef, useState} from 'react';
import {request, type DataSource, type SourcePage, type SourceAccountPage} from './api';
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
  const [accounts, setAccounts] = useState<SourceAccountPage|null>(null);
  const [accountToken, setAccountToken] = useState('');
  const [accountLabel, setAccountLabel] = useState('');
  const [accountOffset, setAccountOffset] = useState(0);
  const [accountQuery, setAccountQuery] = useState('');
  const [accountBusy, setAccountBusy] = useState(false);
  const [accountError, setAccountError] = useState('');
  const accountGeneration = useRef(0);
  const generation = useRef(0);
  useEffect(() => {
    const current = ++accountGeneration.current;
    setAccountBusy(true); setAccountError('');
    void request<SourceAccountPage>('/data-sources/' + source + '/accounts?limit=' + LIMIT
      + '&offset=' + accountOffset + '&q=' + encodeURIComponent(accountQuery))
      .then(result => {if (current === accountGeneration.current) setAccounts(result);})
      .catch(() => {if (current === accountGeneration.current) setAccountError('Account options unavailable.');})
      .finally(() => {if (current === accountGeneration.current) setAccountBusy(false);});
    return () => {accountGeneration.current++;};
  }, [source, accountOffset, accountQuery]);
  const load = useCallback(async (selected: DataSource, start: number, account = '', refresh = false) => {
    const current = ++generation.current;
    setBusy(true); setError(''); setPage(null);
    try {
      const result = await request<SourcePage>('/data-sources/' + selected + (refresh ? '/refresh'
        : '/transactions?limit=' + LIMIT + '&offset=' + start
          + (account ? '&account_token=' + encodeURIComponent(account) : '')), refresh ? {method: 'POST', body: '{}'} : undefined);
      if (current === generation.current) {
        setPage(result);
        if (refresh) {setOffset(0); setAccountToken('');}
      }
    } catch (e) {
      if (current === generation.current) setError(e instanceof Error ? e.message : 'Source unavailable.');
    } finally {if (current === generation.current) setBusy(false);}
  }, []);
  useEffect(() => {
    void load(source, offset, accountToken);
    return () => {generation.current++;};
  }, [source, offset, accountToken, load]);
  function select(next: DataSource) {
    generation.current++; accountGeneration.current++; setPage(null); setOffset(0); setSource(next);
    setAccountToken(''); setAccounts(null); setAccountOffset(0); setAccountQuery('');
  }
  function move(next: number) {generation.current++; setPage(null); setOffset(next);}
  return <section id="V-SOURCES" className="panel fill" lang="en" aria-label="Source transactions" aria-busy={busy}>
    <div className="sectiontop"><div className="actions" role="group" aria-label="Transaction data source">
      {(['nessie', 'banksim'] as const).map(value => <button key={value} id={'S-' + value.toUpperCase()}
        aria-pressed={source === value} disabled={source === value} onClick={() => select(value)}>
        {value === 'nessie' ? 'Nessie' : 'BankSim'}</button>)}
    </div>{source === 'nessie' && <button id="S-REFRESH" disabled={busy}
      onClick={() => void load('nessie', 0, accountToken, true)}>Refresh Nessie</button>}</div>
    {(!!accounts?.total || !!accountQuery || !!accountToken) && <div className="actions" aria-label="Local demo accounts">
      <label>Find account<input id="S-ACCOUNT-SEARCH" value={accountQuery} maxLength={80}
        onChange={event => {accountGeneration.current++; setAccounts(null); setAccountOffset(0); setAccountQuery(event.target.value);}}/></label>
      <label>Local demo account<select id="S-ACCOUNT" value={accountToken} disabled={accountBusy}
        onChange={event => {
          generation.current++; setPage(null); setOffset(0); setAccountToken(event.target.value);
          setAccountLabel(accounts?.items.find(row => row.account_token === event.target.value)?.label ?? '');
        }}><option value="">Original source data</option>
        {accountToken && !accounts?.items.some(row => row.account_token === accountToken)
          && <option value={accountToken}>{accountLabel}</option>}
        {accounts?.items.map(row => <option key={row.account_token} value={row.account_token}>
          {row.label} · {row.transaction_count} transactions</option>)}</select></label>
      <button id="S-ACCOUNT-PREV" disabled={accountBusy || !accountOffset}
        onClick={() => setAccountOffset(Math.max(0, accountOffset - LIMIT))}>Previous accounts</button>
      <span>{accounts ? accounts.total.toLocaleString() + ' accounts' : 'Loading accounts…'}</span>
      <button id="S-ACCOUNT-NEXT" disabled={accountBusy || accounts?.next_offset == null}
        onClick={() => setAccountOffset(accounts!.next_offset!)}>Next accounts</button>
    </div>}
    {accountError && <p role="alert" className="error">{accountError}</p>}
    {accountToken && <p role="status">Local synthetic history · 100 generated records per account. Fraud labels stay offline.</p>}
    <p>{source === 'banksim'  ? 'BankSim research data · EUR · simulation days. Labels and model results are not shown.'
      : 'Nessie sandbox · cached normalized transactions. Refresh explicitly to fetch the sandbox.'}</p>
    {busy && <p role="status">Loading source transactions…</p>}
    {error && <p className="error" role="alert">{error}{' '}<button onClick={() => void load(source, offset, accountToken)}>Retry</button></p>}
    {page && <>
      <div className="admin-meta"><b>{page.total.toLocaleString()} transactions</b>
        <Chip tone={page.data_mode === 'degraded' ? 'warn' : 'neutral'}>{page.data_mode}</Chip>
        {page.last_synced_at && <span>Last collection success: {page.last_synced_at}</span>}</div>
      {page.data_mode === 'degraded' && <p role="status">Refresh was incomplete. These are cached records.</p>}
      {page.items.length ? <div className="paged" key={source + accountToken + offset}>
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
