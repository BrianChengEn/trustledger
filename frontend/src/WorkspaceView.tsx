import {useEffect, useRef} from 'react';
import Activity from './Activity';
import Case from './Case';
import MemoryView from './MemoryView';
import PrivacyView from './PrivacyView';
import type {Route} from './route';
import Today from './Today';
import {Toasts} from './ui';
import {useWorkspace} from './workspace';

export default function WorkspaceView({route}: {route: Route}) {
  const {loaded, loading, ready, error, notice, refresh, dismissNotice, busy} = useWorkspace();
  const previousView = useRef(route.view);
  useEffect(() => {
    if (route.view === 'memory' && previousView.current !== 'memory') {
      if (loading || busy) return;
      previousView.current = route.view;
      void refresh();
    }
    previousView.current = route.view;
  }, [route.view, refresh, loading, busy]);
  return <div className="workspace" style={{display: 'contents'}}>
    <Toasts error={error} notice={notice} busy={loading || busy} onRetry={() => void refresh()} onDismiss={dismissNotice}/>
    {route.view === 'sources' ? null
      : !loaded ? (loading ? <p className="loading" role="status">Loading your workspace…</p> : null)
      : !ready && route.view === 'today'
      ? <p className="loading" role="status">{loading ? 'Loading your workspace…' : 'Rule checks unavailable. Retry before reviewing alerts.'}</p>
      : route.view === 'today' ? <Today/>
      : route.view === 'activity' ? <Activity key={route.filter ?? 'all'} initial={route.filter}/>
      : route.view === 'privacy' ? <PrivacyView txId={route.tx}/>
      : route.view === 'memory' ? <MemoryView/>
      : route.view === 'case' ? <Case key={route.tx} id={route.tx} from={route.from}/> : null}
  </div>;
}

export function CustomerReview({route}: {route: Route}) {
  const {href} = useWorkspace();
  return <>
    <nav className="actions" aria-label="Customer workspace">
      {(['today', 'activity', 'privacy', 'memory'] as const).map(view => <a key={view} className="navlink"
        aria-current={route.view === view ? 'page' : undefined} href={href({view})}>{view[0].toUpperCase() + view.slice(1)}</a>)}
    </nav>
    <WorkspaceView route={route}/>
  </>;
}
