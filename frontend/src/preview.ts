import {useEffect, useState} from 'react';
import {request, type PrivacyPreview} from './api';
import {useWorkspace} from './workspace';

/** Loads the backend serializer's real preview. Reloads when saved memory changes (it feeds prior_user_confirmation). */
export function usePreview(transactionId: string | undefined, memoryKey: string) {
  const {prefix, revision, ready} = useWorkspace();
  const [state, setState] = useState<{key: string; preview?: PrivacyPreview; failed?: boolean} | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = [prefix, transactionId, memoryKey, revision, attempt].join('|');
  useEffect(() => {
    if (!transactionId || !ready) { setState(null); return; }
    let active = true;
    request<PrivacyPreview>(prefix + '/privacy/preview/' + encodeURIComponent(transactionId))
      .then(preview => { if (active) setState({key, preview}); })
      .catch(() => { if (active) setState({key, failed: true}); });
    return () => { active = false; };
  }, [transactionId, key, prefix, ready]);
  const current = ready && state?.key === key ? state : null;
  return {preview: current?.preview ?? null, failed: !!current?.failed,
    loading: ready && !!transactionId && !current, retry: () => { setState(null); setAttempt(n => n + 1); }};
}
