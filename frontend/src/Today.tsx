import {labels, money} from './api';
import {Icon, type IconName} from './icons';
import {alertHints, byPriority, day, ruleCoverage} from './lib';
import {useState} from 'react';
import {PageNav} from './Pager';
import {Chip, PageHead, stagger} from './ui';
import Widgets from './Widgets';
import {useWorkspace} from './workspace';

export const alertIcons: Record<string, IconName> = {
  duplicate: 'copy', amount_anomaly: 'alertTriangle', subscription_change: 'trendingUp', none: 'checkCircle',
};
export const statusText = {open: 'Waiting for you', normal: 'You marked it normal', review: 'You marked it for review'} as const;

/** Today answers one question: does anything need me, and what first? It never lists every transaction. */
export default function Today() {
  const {alerts, transactions, memories, ready, go} = useWorkspace();
  const insufficient = transactions.filter(tx => ruleCoverage(tx) === 'Insufficient evidence').length;
  const ordered = byPriority(alerts, transactions);
  const open = ordered.filter(a => a.status === 'open');
  const decided = ordered.length - open.length;
  const first = open[0];
  const tx = (id: string) => transactions.find(t => t.id === id);
  const firstTx = first && tx(first.transaction_id);
  const count = (s: string) => ordered.filter(a => a.status === s).length;
  // The queue shows three alerts at a time; the page buttons move between them.
  const PER_PAGE = 3;
  const [page, setPageRaw] = useState(0);
  const pages = Math.max(1, Math.ceil(ordered.length / PER_PAGE));
  const current = Math.min(page, pages - 1);
  const setPage = (next: number) => setPageRaw(Math.max(0, Math.min(pages - 1, next)));
  const shown = ordered.slice(current * PER_PAGE, current * PER_PAGE + PER_PAGE);
  const flaggedValue = open.reduce((n, a) => n + (tx(a.transaction_id)?.amount ?? 0), 0);

  return <div className="page today">
    <PageHead eyebrow="Today" title={!ready ? 'Analysis unavailable.' : open.length ? `${open.length} ${open.length === 1 ? 'charge needs' : 'charges need'} your eyes.` : insufficient ? 'Some transactions need more evidence.' : 'Nothing needs you right now.'}>
      {!ready ? 'Analysis is unavailable. Refresh before drawing a conclusion.' : open.length
        ? `${money(flaggedValue)} across flagged charges. Rules found them; you decide what they mean. Nothing changes until you do.`
        : insufficient ? `${insufficient} transactions have insufficient evidence. An absent alert is not a safe verdict.` : `${transactions.length} transactions checked by the rules. ${decided} flagged ${decided === 1 ? 'charge was' : 'charges were'} reviewed by you.`}
    </PageHead>

    {first && firstTx && <section className="startcard" aria-labelledby="start-title">
      <div className="startmain">
        <Chip tone="warn" icon="compass">Start here · {first.severity} priority</Chip>
        <h2 id="start-title">{labels[first.alert_type]}: {firstTx.merchant_display}, {money(firstTx.amount)}</h2>
        <p>{first.evidence[0]}</p>
      </div>
      <div className="startside">
        <div className="startamount" aria-hidden="true"><span>{day(firstTx.occurred_at)}</span><strong>{money(firstTx.amount)}</strong></div>
        <button className="primary" onClick={() => go({view: 'case', tx: first.transaction_id, from: 'today'})}>
          Review this charge<Icon name="arrowRight" size={16}/></button>
      </div>
    </section>}

    {!!ordered.length && <section className="panel queuepanel" aria-labelledby="queue-title">
      <div className="sectiontop">
        <h2 id="queue-title">{open.length ? 'Review queue' : 'Reviewed alerts'}</h2>
        <div className="progress" role="img" aria-label={`${open.length} open, ${count('normal')} marked normal, ${count('review')} marked for review`}>
          {ordered.map(a => <i key={a.alert_id} className={'seg-' + a.status}/>)}
        </div>
      </div>
      <ul className="queue">
        {shown.map((a, i) => {
          const t = tx(a.transaction_id);
          const prior = memories.length > 0 && a.evidence.some(e => e.startsWith('A prior consented'));
          return <li key={a.alert_id} style={stagger(i)}>
            <button className={'queuerow status-' + a.status} onClick={() => go({view: 'case', tx: a.transaction_id, from: 'today'})}>
              <span className={'icontile ' + (a.status === 'open' ? 'alert' : '')}><Icon name={a.status === 'open' ? alertIcons[a.alert_type] : 'checkCircle'} size={20}/></span>
              <span className="qtext"><b>{labels[a.alert_type]}</b>
                <small>{t?.merchant_display} · {t && day(t.occurred_at)} · {alertHints[a.alert_type]}</small></span>
              {prior && <Chip tone="good" icon="hardDrive">Uses your memory</Chip>}
              <span className="qside"><strong>{t ? money(t.amount) : ''}</strong>
                <small className={'state-' + a.status}>{statusText[a.status]}</small></span>
              <Icon name="arrowRight" size={16}/>
            </button>
          </li>;
        })}
      </ul>
      <PageNav page={current} pages={pages} onPage={setPage}/>
    </section>}

    {!ordered.length && <div className="empty">
      <Icon name={insufficient ? 'info' : 'shieldCheck'} size={28}/><p>{ready ? `No rule flagged any of your ${transactions.length} transactions.` : 'Analysis is unavailable; no completed check is claimed.'}</p></div>}

    <Widgets/>
  </div>;
}
