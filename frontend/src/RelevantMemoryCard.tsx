import {Icon} from './icons';
import {memoryStore, prettyCategory} from './lib';
import {verificationLine, type RelevantView} from './relevant';
import {Chip} from './ui';
import {useWorkspace} from './workspace';

/** Renders one card state. Shared with the Memory Lab so both show exactly the same wording. */
export function RelevantResult({view, retry}: {view: RelevantView; retry?: () => void}) {
  return <>
    {view.kind === 'loading' && <p className="quiet" role="status">Checking your saved memories…</p>}
    {view.kind === 'found' && view.memories.map(m => <div key={m.memory_id} className="relevantfound">
      <b>Relevant memory found</b>
      <blockquote className="memtext"><Icon name="hardDrive" size={14}/>{m.summary}</blockquote>
      <small>{memoryStore(m.source).label} · {verificationLine(m.verification)}</small></div>)}
    {view.kind === 'empty' && <p><b>No relevant memory found.</b> <span className="quiet">No eligible matching consented memory is available.</span></p>}
    {view.kind === 'unavailable' && <p><b>Memory could not be checked right now.</b> <span className="quiet">No saved sentence is shown.{retry && <> <button className="linklike" onClick={retry}>Try again</button></>}</span></p>}
    {view.kind === 'error' && <p role="alert"><b>Memory could not be loaded.</b> <span className="quiet">No saved sentence is shown.{retry && <> <button className="linklike" onClick={retry}>Try again</button></>}</span></p>}
  </>;
}

/** Step between "why it was flagged" and "your decision": consented context for this category. Never changes the alert. */
export default function RelevantMemoryCard({view, retry, category, failure, requiresReview = true}: {view: RelevantView; retry: () => void; category: string; failure?: string|null; requiresReview?: boolean}) {
  const {href} = useWorkspace();
  return <section className="relevant" aria-labelledby="relevant-title" aria-live="polite">
    <div className="relevanthead"><span className="icontile small"><Icon name="hardDrive" size={14}/></span>
      <h2 id="relevant-title">Relevant memory</h2>
      <Chip>{prettyCategory(category)}</Chip></div>
    {category === 'other' && view.kind === 'empty'
      ? <p>No relevance claim: this transaction has no specific category evidence.</p>
      : <RelevantResult view={view} retry={retry}/>}
    {failure && <p className="quiet">Provider verification is incomplete. No complete remote verification is claimed.</p>}
    <p className="relevantnote"><Icon name="user" size={14}/><span><b>{requiresReview ? 'This transaction still requires review.' : 'An absent open alert does not establish safety.'}</b> Memory adds context only. The alert and your decision are unchanged.
      {' '}<a href={href({view: 'memory'})}>Manage in Memory</a> · <a href={href({view: 'memory', lab: ''})}>See how memory works</a></span></p>
  </section>;
}
