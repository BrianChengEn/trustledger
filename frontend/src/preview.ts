import {useEffect, useState} from 'react';
import {request, type PrivacyPreview} from './api';

/** Loads the backend serializer's real preview. Reloads when saved memory changes (it feeds prior_user_confirmation). */
export function usePreview(transactionId: string | undefined, memoryKey: string) {
  const [state, setState] = useState<{id: string; preview?: PrivacyPreview; failed?: boolean} | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!transactionId) { setState(null); return; }
    let active = true;
    request<PrivacyPreview>('/privacy/preview/' + encodeURIComponent(transactionId))
      .then(preview => { if (active) setState({id: transactionId, preview}); })
      .catch(() => { if (active) setState({id: transactionId, failed: true}); });
    return () => { active = false; };
  }, [transactionId, memoryKey, attempt]);
  const current = state?.id === transactionId ? state : null;
  return {preview: current?.preview ?? null, failed: !!current?.failed,
    loading: !!transactionId && !current, retry: () => { setState(null); setAttempt(n => n + 1); }};
}
