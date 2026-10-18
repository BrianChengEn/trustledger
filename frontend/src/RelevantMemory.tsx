import {useEffect, useState} from 'react';
import {request, type RelevantMemories} from './api';
import {useWorkspace} from './workspace';

/** Context comes from the consent/owner-filtered endpoint, never the management list. */
export default function RelevantMemory({transactionId, category}: {transactionId: string; category: string}) {
  const {prefix, ready, memoryKey, revision} = useWorkspace();
  const [result, setResult] = useState<RelevantMemories | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setResult(null); setFailed(false);
    if (ready) void request<RelevantMemories>(prefix + '/transactions/' + encodeURIComponent(transactionId) + '/relevant-memories')
      .then(value => { if (active) setResult(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [prefix, transactionId, ready, memoryKey, revision]);
  return <div className="memnote" aria-label="Relevant memory context">
    <div><b>Historical context</b>
      {!ready || failed || result?.retrieval_mode === 'unavailable'
        ? <p>Memory context is unavailable. The rules result and your decision remain unchanged.</p>
        : !result ? <p>Checking consented context…</p>
        : category === 'other' ? <p>No relevance claim: this transaction has no specific category evidence.</p>
        : !result.memories.length ? <p>No matching consented memory.</p>
        : <>{result.memories.map(memory => <p key={memory.memory_id}>{memory.summary} <small>
          {memory.verification === 'remote_verified' ? 'Remote content verified.' : memory.verification === 'local_only' ? 'Local context only.' : 'Remote content unverified.'}
        </small></p>)}<p>Context only. Earlier confirmations never clear this alert or approve a future transaction.</p></>}
      {result?.failure && <p>Provider verification is incomplete. No remote verification is claimed.</p>}
    </div>
  </div>;
}
