import {useEffect, useState} from 'react';
import {request, type RelevantMemoryResult} from './api';
import {Icon} from './icons';
import {prettyCategory, relevantMemoryCopy} from './lib';
import {Chip} from './ui';
import {useWorkspace} from './workspace';

type State = {key: string; data: RelevantMemoryResult | null};

/** Consented same-category context for an alert. Read-only: it never changes or hides the alert. */
export default function RelevantMemory({transactionId}: {transactionId: string}) {
  const {prefix, ready, memoryKey, revision, forget, busy} = useWorkspace();
  const [attemptNo, setAttemptNo] = useState(0);
  const [state, setState] = useState<State | null>(null);
  const [confirming, setConfirming] = useState(false);
  const fullKey = [transactionId, prefix, memoryKey, revision, attemptNo].join('|');

  useEffect(() => {
    if (!ready) return;
    let active = true;
    setConfirming(false);
    // A failed or unmatched lookup is an explicit state: stale memory is never kept on screen.
    request<RelevantMemoryResult>(prefix + '/transactions/' + encodeURIComponent(transactionId) + '/relevant-memory')
      .then(data => { if (active) setState({key: fullKey, data}); })
      .catch(() => { if (active) setState({key: fullKey, data: null}); });
    return () => { active = false; };
  }, [fullKey, ready, prefix, transactionId]);

  const current = state?.key === fullKey ? state : null;
  if (!ready) return null;
  if (!current) return <section className="relmem" aria-labelledby="relmem-title" aria-busy="true">
    <h3 id="relmem-title"><Icon name="hardDrive" size={15}/>Relevant memory</h3>
    <p className="quiet" role="status">Checking for memory you consented to…</p></section>;

  const r = current.data;
  const copy = relevantMemoryCopy(r ?? {memory_status: 'unavailable', retrieval: null, summary: null});
  const showMemory = !!r && copy.hasMemory && r.summary;
  return <section className={'relmem tone-' + copy.tone} aria-labelledby="relmem-title">
    <div className="steptop"><h3 id="relmem-title"><Icon name="hardDrive" size={15}/>Relevant memory</h3>
      <Chip tone={copy.tone === 'good' ? 'good' : copy.tone === 'warn' ? 'warn' : 'neutral'}>{copy.chip}</Chip></div>
    <p><b>{copy.title}</b></p>
    {showMemory && <>
      <blockquote>{r.summary}</blockquote>
      <p className="quiet">Matched on the same category ({prettyCategory(r.category)}). {copy.detail}</p>
      <p className="stillreview" role="status"><Icon name="alertTriangle" size={15}/>This transaction still requires review.</p>
      {r.memory_id && <div className="actions">{confirming ? <>
        <button className="danger" disabled={busy} onClick={async () => { const id = r.memory_id!; if (!(await forget(id))) setConfirming(false); }}>
          <Icon name="trash" size={15}/>{busy ? 'Deleting…' : 'Yes, delete this memory'}</button>
        <button disabled={busy} onClick={() => setConfirming(false)}>Keep it</button></>
        : <button onClick={() => setConfirming(true)}><Icon name="trash" size={15}/>Delete memory</button>}</div>}
    </>}
    {!showMemory && <p className="quiet">{copy.detail}</p>}
    {!r && <div className="actions"><button onClick={() => { setState(null); setAttemptNo(n => n + 1); }}>Try again</button></div>}
  </section>;
}
