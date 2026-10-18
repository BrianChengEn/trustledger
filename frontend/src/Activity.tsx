import {useMemo, useState} from 'react';
import {labels, money} from './api';
import {Icon, type IconName} from './icons';
import Pager from './Pager';
import {dataModeCopy, day, prettyCategory, time} from './lib';
import {alertIcons} from './Today';
import {Chip, PageHead, Seg, stagger} from './ui';
import {useWorkspace} from './workspace';

type Filter = 'all' | 'flagged' | 'recurring';
type Sort = 'newest' | 'largest';
const categoryIcons: Record<string, IconName> = {
  dining: 'coffee', groceries: 'cart', streaming: 'tv', electronics: 'laptop',
  transportation: 'bus', fitness_subscription: 'activity',
};
export const categoryIcon = (name: string): IconName => categoryIcons[name] ?? 'circle';

/** Activity is the full ledger: find any transaction, whatever its alert status. */
export default function Activity({initial}: {initial?: string}) {
  const {transactions, alerts, health, ready, go, href} = useWorkspace();
  const [filter, setFilter] = useState<Filter>(initial === 'flagged' || initial === 'recurring' ? initial : 'all');
  const [sort, setSort] = useState<Sort>('newest');
  const [query, setQuery] = useState('');
  const alertFor = (id: string) => alerts.find(a => a.transaction_id === id);
  const counts = {all: transactions.length, flagged: transactions.filter(t => alertFor(t.id)).length,
    recurring: transactions.filter(t => t.is_subscription).length};
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return transactions
      .filter(t => filter === 'all' || (filter === 'flagged' ? alerts.some(a => a.transaction_id === t.id) : t.is_subscription))
      .filter(t => !q || t.merchant_display.toLowerCase().includes(q) || prettyCategory(t.merchant_category).includes(q))
      .sort((a, b) => sort === 'newest' ? b.occurred_at.localeCompare(a.occurred_at) : b.amount - a.amount);
  }, [transactions, alerts, filter, sort, query]);
  const sources = [...new Set(transactions.map(t => t.source))];
  const data = dataModeCopy(ready ? health?.data_mode : 'degraded');

  return <div className="page activity">
    <PageHead eyebrow="Activity" title="Every transaction.">
      Open any charge to see how it was checked, flagged or not.</PageHead>
    <p className="sourceline"><Icon name="database" size={15}/>
      <span><b>{data.label}.</b> {sources.length ? `All ${transactions.length} records here come from: ${sources.join(', ')}.` : ''}{' '}
        <a href={href({view: 'sources'})}>Where does this data come from?</a></span></p>
    <section className="panel fill">
      <div className="toolbar">
        <Seg label="Filter transactions" value={filter} onChange={setFilter} options={[
          {key: 'all', label: 'All', count: counts.all}, {key: 'flagged', label: 'Flagged', count: counts.flagged},
          {key: 'recurring', label: 'Recurring', count: counts.recurring}]}/>
        <label className="search"><Icon name="search" size={15}/><span className="visually-hidden">Search merchant or category</span>
          <input type="search" placeholder="Search merchant or category" value={query} onChange={e => setQuery(e.target.value)}/></label>
        <label className="sortpick"><span>Sort</span>
          <select value={sort} onChange={e => setSort(e.target.value as Sort)}>
            <option value="newest">Newest first</option><option value="largest">Largest first</option></select></label>
      </div>
      {rows.length ? <div className="paged" key={filter + ':' + sort + ':' + query}><div className={'tablewrap' + (rows.length >= 6 ? ' stretch' : '')}><table className="txtable">
        <thead><tr><th>Merchant</th><th>When</th><th>Check result</th><th className="amount">Amount</th></tr></thead>
        <tbody>{rows.map((t, i) => {
          const a = alertFor(t.id);
          return <tr key={t.id} style={stagger(i)} className="clickrow">
            <td data-label="Merchant"><button className="rowlink" onClick={() => go({view: 'case', tx: t.id, from: 'activity'})}>
              <span className="icontile small"><Icon name={categoryIcon(t.merchant_category)} size={16}/></span>
              <span><b>{t.merchant_display}</b><small>{prettyCategory(t.merchant_category)}{t.is_subscription ? ' · recurring' : ''} · {t.source}</small></span></button></td>
            <td data-label="When">{t.date_only ? t.occurred_at.slice(0, 10) : day(t.occurred_at)}<small>{t.date_only ? 'Date only' : time(t.occurred_at)}</small></td>
            <td data-label="Check result">{!ready ? <Chip>Analysis unavailable</Chip> : a
              ? <Chip tone={a.status === 'open' ? 'warn' : 'neutral'} icon={alertIcons[a.alert_type]}>{labels[a.alert_type]}{a.status !== 'open' && ` · ${a.status === 'normal' ? 'normal' : 'review'}`}</Chip>
              : <Chip icon="check">No rule triggered</Chip>}</td>
            <td data-label="Amount" className="amount">{money(t.amount)}</td>
          </tr>;
        })}</tbody>
      </table></div><Pager/></div>
      : <div className="empty"><Icon name="search" size={24}/><p>No transactions match{query ? ` “${query}”` : ' this filter'}.</p>
        <button onClick={() => { setQuery(''); setFilter('all'); }}>Clear filters</button></div>}
    </section>
  </div>;
}
