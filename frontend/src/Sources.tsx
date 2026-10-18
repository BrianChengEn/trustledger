import {Icon} from './icons';
import {dataModeCopy} from './lib';
import Admin from './Admin';
import {Chip, PageHead} from './ui';
import {useWorkspace} from './workspace';

/** Sources answers: where does the data come from, and is the Nessie sandbox part of this workspace? */
export function SourcesIntro() {
  const {health, transactions} = useWorkspace();
  const data = dataModeCopy(health?.data_mode);
  const counts = transactions.reduce<Record<string, number>>((n, t) => ({...n, [t.source]: (n[t.source] ?? 0) + 1}), {});
  return <>
    <PageHead eyebrow="Data sources" title="Where your transactions come from.">
      The workspace works the same whichever source feeds it.</PageHead>
    <div className="sourcegrid">
      <section className="panel">
        <div className="sectiontop"><h2><Icon name="wallet" size={18}/>This workspace</h2><Chip tone={data.tone}>{data.label}</Chip></div>
        <p>{data.detail}</p>
        <ul className="plainlist">{Object.entries(counts).map(([source, n]) =>
          <li key={source}><b>{n}</b> {n === 1 ? 'transaction' : 'transactions'} from <b>{source === 'synthetic' ? 'synthetic fixtures' : 'the Nessie sandbox'}</b></li>)}</ul>
      </section>
      <section className="panel">
        <div className="sectiontop"><h2><Icon name="database" size={18}/>Capital One Nessie sandbox</h2><Chip>Read-only console</Chip></div>
        <p>The console below runs read-only Nessie queries through the backend. Results are de-identified, and history keeps only status and timing.{' '}
          {health?.data_mode === 'synthetic'
          ? 'Queries here do not feed the transactions in this workspace, which are synthetic fixtures.'
          : 'Check the workspace card for the source that feeds your transactions.'}</p>
      </section>
    </div>
  </>;
}
export { Admin };
