import type {ReactElement} from 'react';
import {Icon} from '../icons';
import {go} from '../route';
import {Chip} from '../ui';
import Architecture from './Architecture';
import Arena from './Arena';
import Challenge from './Challenge';
import {provenance} from './data';
import Evaluation from './Evaluation';
import {CHAPTERS, type ChapterId} from './facts';
import Features from './Features';
import Explorer from './Explorer';
import Overview from './Overview';

const screens: Record<ChapterId, () => ReactElement> = {
  overview: Overview, challenge: Challenge, features: Features, architecture: Architecture, evaluation: Evaluation, explorer: Explorer, arena: Arena,
};

/** Fraud Intelligence Lab: an offline research showcase (System B). It never calls the backend, a provider, or any model. */
export default function FraudLab({chapter}: {chapter?: string}) {
  const index = Math.max(0, CHAPTERS.findIndex(c => c.id === chapter));
  const current = CHAPTERS[index];
  const Screen = screens[current.id];
  const open = (id: ChapterId) => go({view: 'fraudlab', chapter: id === 'overview' ? undefined : id});
  return <div className="page fl">
    <header className="fl-head">
      <div><div className="eyebrow">Fraud Intelligence Lab</div><h1>{current.title}</h1></div>
      <div className="fl-system"><Chip tone="ai" icon="sparkles">System B · offline research</Chip>
        <small className="quiet">Not the product’s live alerts. Synthetic BankSim data.</small></div>
    </header>
    <div className="fl-body">
      <nav className="fl-rail" aria-label="Chapters">
        <ol>{CHAPTERS.map((c, i) => <li key={c.id}><button type="button" aria-current={i === index ? 'step' : undefined} className={i < index ? 'done' : ''}
          onClick={() => open(c.id)}>{c.short}</button></li>)}</ol>
        <p className="quiet fl-prov">Every number comes from saved benchmark artifacts at commit <span className="mono">{provenance.leaderboard_last_changed_in_commit.slice(0, 7)}</span>.</p>
      </nav>
      <main className="fl-stage" aria-labelledby="fl-title" key={current.id}>
        <Screen/>
        <div className="fl-pager">
          <button type="button" disabled={index === 0} onClick={() => open(CHAPTERS[index - 1].id)}><Icon name="arrowLeft" size={15}/>Previous</button>
          <button type="button" className="primary" disabled={index === CHAPTERS.length - 1} onClick={() => open(CHAPTERS[index + 1].id)}>Next chapter<Icon name="arrowRight" size={15}/></button>
        </div>
      </main>
    </div>
  </div>;
}
