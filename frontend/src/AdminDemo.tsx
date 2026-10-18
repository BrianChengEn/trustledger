import {useCallback, useEffect, useState, type FormEvent} from 'react';
import {ApiError, money, request, type DemoInput, type DemoLog, type DemoRow, type DemoStatus, type ResetResult, type Scenario, type ScenarioResult} from './api';
import {Icon, type IconName} from './icons';
import {day, prettyCategory, time} from './lib';
import Pager from './Pager';
import {go, useRoute} from './route';
import {Callout, Chip, PageHead, Seg, stagger, Toasts} from './ui';
import {categoryIcon} from './Activity';
import {useWorkspace} from './workspace';

const CATEGORIES = ['dining', 'groceries', 'streaming', 'electronics', 'transportation', 'fitness_subscription', 'other'];
const pad = (n: number) => String(n).padStart(2, '0');
const localInput = (iso: string) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const blank = () => ({merchant: '', category: 'dining', amount: '', when: localInput(new Date().toISOString()), direction: 'debit' as 'debit' | 'credit', recurring: false});
type Form = ReturnType<typeof blank>;

const problems: Record<string, string> = {
  row_cap: 'The demo is full (60 charges). Delete a few or reset the demo.',
  decision_exists: 'The user already decided this charge, so it cannot be changed. Reset the demo to start clean.',
  remote_memory_exists: 'A memory saved on Backboard exists. Delete it from the user’s Memory page first, then reset.',
  demo_edit_disabled: 'Demo editing is switched off on this server. Set ALLOW_DEMO_EDIT=true in backend/.env and restart the backend.',
  not_synthetic_mode: 'This server is showing Nessie data, not synthetic data, so there is nothing here to edit.',
  not_found: 'That charge no longer exists. The list was refreshed.',
  invalid_request: 'Check the fields: a merchant, a positive amount with at most two decimals, and a date.',
  admin_only: 'Only an admin can change the demo data.',
};
const explain = (e: unknown) => e instanceof ApiError && e.code && problems[e.code] ? problems[e.code]
  : 'That did not work. Try again, or check that the backend is running.';

const SCENARIOS: {key: Scenario; icon: IconName; title: string; text: string}[] = [
  {key: 'duplicate', icon: 'copy', title: 'Inject a duplicate charge', text: 'Two identical charges minutes apart.'},
  {key: 'large_purchase', icon: 'alertTriangle', title: 'Inject a large purchase', text: 'One charge well above the usual amount.'},
  {key: 'price_hike', icon: 'trendingUp', title: 'Inject a price hike', text: 'A subscription that jumps by 50%.'},
];
const actionLabel = {create: 'Added', update: 'Changed', delete: 'Deleted', scenario: 'Scenario', reset: 'Reset'} as const;

/** Admin: edit the synthetic demo data, then show how the app reacts. Everything here is synthetic. */
export default function AdminDemo() {
  const route = useRoute();
  const {refresh} = useWorkspace();
  const tab = route.view === 'admin' && route.tab === 'log' ? 'log' : 'charges';
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [rows, setRows] = useState<DemoRow[]>([]);
  const [log, setLog] = useState<DemoLog[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<Form>(blank);
  const [editing, setEditing] = useState<string | null>(null);
  const [fieldProblem, setFieldProblem] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(async () => {
    try {
      const view = await request<DemoStatus>('/admin/demo/status');
      setStatus(view);
      if (view.enabled) {
        const [list, changes] = await Promise.all([request<DemoRow[]>('/admin/demo/transactions'), request<DemoLog[]>('/admin/demo/log?limit=100')]);
        setRows(list); setLog(changes);
      } else { setRows([]); setLog([]); }
      setError('');
    } catch (e) { setError(explain(e)); }
    finally { setLoaded(true); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  /** One admin action: run it, reload the list, and refresh the user's data so the preview shows the effect. */
  async function act(work: () => Promise<string>) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const message = await work();
      await load(); void refresh();
      setNotice(message);
    } catch (e) { setError(explain(e)); await load(); }
    finally { setBusy(false); }
  }

  const fields = (event: FormEvent) => {
    event.preventDefault();
    const amount = Number(form.amount);
    if (!form.merchant.trim() || !(amount > 0) || amount > 99999.99 || !form.when) {
      setFieldProblem('Enter a merchant, an amount above $0 (up to $99,999.99), and a date.'); return;
    }
    setFieldProblem('');
    const body: DemoInput = {merchant: form.merchant.trim(), category: form.category, amount: Math.round(amount * 100) / 100,
      occurred_at: new Date(form.when).toISOString(), direction: form.direction, is_subscription: form.recurring};
    void act(async () => {
      if (editing) {
        await request('/admin/demo/transactions/' + encodeURIComponent(editing), {method: 'PATCH', body: JSON.stringify(body)});
        setEditing(null); setForm(blank());
        return `Saved ${body.merchant}, ${money(body.amount)}.`;
      }
      await request<DemoRow>('/admin/demo/transactions', {method: 'POST', body: JSON.stringify(body)});
      setForm(blank());
      return `Added ${body.merchant}, ${money(body.amount)}. Preview the user view to see whether it raises an alert.`;
    });
  };
  const edit = (row: DemoRow) => {
    setEditing(row.id); setFieldProblem(''); setDeleting(null);
    setForm({merchant: row.merchant_display, category: row.merchant_category, amount: String(row.amount), when: localInput(row.occurred_at),
      direction: row.direction === 'credit' ? 'credit' : 'debit', recurring: row.is_subscription});
  };
  const cancelEdit = () => { setEditing(null); setForm(blank()); setFieldProblem(''); };
  const remove = (row: DemoRow) => void act(async () => {
    await request('/admin/demo/transactions/' + encodeURIComponent(row.id), {method: 'DELETE'});
    setDeleting(null); if (editing === row.id) cancelEdit();
    return `Deleted ${row.merchant_display}.`;
  });
  const inject = (scenario: Scenario) => void act(async () => {
    const result = await request<ScenarioResult>('/admin/demo/scenarios/' + scenario, {method: 'POST', body: '{}'});
    const last = result.created[result.created.length - 1];
    return `Added ${result.created.length === 1 ? 'a charge' : result.created.length + ' charges'} (${last.merchant_display}). Preview the user view to see the alert.`;
  });
  const reset = () => void act(async () => {
    const result = await request<ResetResult>('/admin/demo/reset', {method: 'POST', body: '{}'});
    setConfirmReset(false); cancelEdit();
    return `Demo reset: ${result.restored} original charges restored, ${result.cleared_decisions} decisions and ${result.cleared_memories} memories cleared.`;
  });

  const enabled = !!status?.enabled;
  const originChip = (row: DemoRow) => row.origin === 'admin' ? <Chip tone="good">Added</Chip>
    : row.edited_at ? <Chip tone="warn">Edited</Chip> : <Chip>Original</Chip>;

  return <div className="page admindemo">
    <PageHead eyebrow="Admin · Demo data" title="Edit the demo, show the reaction."
      actions={<Seg label="Demo data section" value={tab} onChange={next => go({view: 'admin', tab: next === 'log' ? 'log' : undefined})}
        options={[{key: 'charges', label: 'Charges', count: status?.rows}, {key: 'log', label: 'Changes', count: log.length}]}/>}>
      Everything here is synthetic. Change the data, then preview the user view to watch the alerts react.</PageHead>

    {loaded && !enabled && <Callout tone="warn" icon="alertTriangle" title="Demo editing is off">
      {error || problems[status?.rows === undefined ? 'demo_edit_disabled' : 'demo_edit_disabled']}</Callout>}

    {tab === 'charges' && <>
      <section className="scenarios" aria-label="Scenarios">
        {SCENARIOS.map(s => <button key={s.key} className="scenario" disabled={!enabled || busy} onClick={() => inject(s.key)}>
          <span className="icontile small"><Icon name={s.icon} size={15}/></span><span className="scenariotext"><b>{s.title}</b><small>{s.text}</small></span></button>)}
        <div className={'scenario resetcard' + (confirmReset ? ' asking' : '')}>
          {!confirmReset
            ? <button className="danger" disabled={!enabled || busy} onClick={() => setConfirmReset(true)}><Icon name="refresh" size={15}/>Reset demo</button>
            : <><span className="scenariotext"><b>Reset everything?</b><small>Restores the 18 original charges and clears decisions and memories.</small></span>
              <span className="actions"><button className="danger small" disabled={busy} onClick={reset}>Yes, reset</button>
                <button className="small" disabled={busy} onClick={() => setConfirmReset(false)}>Cancel</button></span></>}
        </div>
      </section>

      <div className="demogrid">
        <section className="panel ledger" aria-label="Demo charges">
          <div className="paged">
            <div className="tablewrap"><table className="txtable">
              <thead><tr><th>Merchant</th><th>When</th><th className="amount">Amount</th><th>Source</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
              <tbody>{rows.map((row, i) => <tr key={row.id} style={stagger(i)} className={editing === row.id ? 'editing' : ''}>
                <td data-label="Merchant"><span className="rowlink"><span className="icontile small"><Icon name={categoryIcon(row.merchant_category)} size={15}/></span>
                  <span><b>{row.merchant_display}</b><small>{prettyCategory(row.merchant_category)}{row.is_subscription ? ' · recurring' : ''}{row.direction === 'credit' ? ' · refund' : ''}</small></span></span></td>
                <td data-label="When">{day(row.occurred_at)}<small>{time(row.occurred_at)}</small></td>
                <td data-label="Amount" className="amount">{money(row.amount)}</td>
                <td data-label="Source">{originChip(row)}</td>
                <td className="rowactions">{row.decided ? <span className="chip" title="The user decided this charge. Reset the demo to change it."><Icon name="lock" size={12}/>Decided</span>
                  : deleting === row.id ? <span className="actions"><button className="danger small" disabled={busy} onClick={() => remove(row)}>Delete</button>
                      <button className="small" onClick={() => setDeleting(null)}>Keep</button></span>
                  : <span className="actions"><button className="iconbtn" aria-label={`Edit ${row.merchant_display}`} disabled={busy} onClick={() => edit(row)}><Icon name="pencil" size={15}/></button>
                      <button className="iconbtn" aria-label={`Delete ${row.merchant_display}`} disabled={busy} onClick={() => setDeleting(row.id)}><Icon name="trash" size={15}/></button></span>}</td>
              </tr>)}</tbody>
            </table></div>
            <Pager/>
          </div>
        </section>

        <form className="panel demoform" onSubmit={fields} aria-label={editing ? 'Edit charge' : 'Add a charge'}>
          <h2><Icon name={editing ? 'pencil' : 'plus'} size={17}/>{editing ? 'Edit charge' : 'Add a charge'}</h2>
          <label>Merchant<input value={form.merchant} maxLength={80} disabled={!enabled || busy} onChange={e => setForm({...form, merchant: e.target.value})} placeholder="e.g. Corner Bistro"/></label>
          <div className="pair">
            <label>Category<select value={form.category} disabled={!enabled || busy} onChange={e => setForm({...form, category: e.target.value})}>
              {CATEGORIES.map(c => <option key={c} value={c}>{prettyCategory(c)}</option>)}</select></label>
            <label>Type<select value={form.direction} disabled={!enabled || busy} onChange={e => setForm({...form, direction: e.target.value as 'debit' | 'credit'})}>
              <option value="debit">Spending</option><option value="credit">Refund</option></select></label>
          </div>
          <div className="pair">
            <label>Amount (USD)<input type="number" step="0.01" min="0.01" max="99999.99" inputMode="decimal" value={form.amount} disabled={!enabled || busy}
              onChange={e => setForm({...form, amount: e.target.value})} placeholder="0.00"/></label>
            <label>Date and time<input type="datetime-local" value={form.when} disabled={!enabled || busy} onChange={e => setForm({...form, when: e.target.value})}/></label>
          </div>
          <label className="checkrow"><input type="checkbox" checked={form.recurring} disabled={!enabled || busy} onChange={e => setForm({...form, recurring: e.target.checked})}/>Recurring subscription</label>
          {fieldProblem && <p className="fieldproblem" role="alert">{fieldProblem}</p>}
          <div className="actions">
            <button className="primary" type="submit" disabled={!enabled || busy}>{editing ? 'Save changes' : 'Add charge'}</button>
            {editing && <button type="button" onClick={cancelEdit} disabled={busy}>Cancel</button>}
          </div>
          <p className="quiet">Only synthetic charges can be created. The server picks the id, account and source.</p>
        </form>
      </div>
    </>}

    {tab === 'log' && <section className="panel changelog" aria-label="Change log">
      {!log.length ? <div className="empty"><Icon name="clock" size={24}/><p>No changes yet. Edits, scenarios and resets appear here.</p></div>
        : <div className="paged"><ul className="changes">{log.map((entry, i) => <li key={entry.id} style={stagger(i)}>
          <Chip tone={entry.action === 'reset' ? 'warn' : entry.action === 'delete' ? 'danger' : 'good'}>{actionLabel[entry.action]}</Chip>
          <span className="changetext">{entry.summary}</span>
          <small>{day(entry.at)} · {time(entry.at)}</small></li>)}</ul><Pager/></div>}
    </section>}

    <Toasts error={error && enabled ? error : ''} notice={notice} busy={busy} onRetry={() => void load()} onDismiss={() => { setNotice(''); setError(''); }}/>
  </div>;
}
