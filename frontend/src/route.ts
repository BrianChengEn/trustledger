import {useEffect, useState} from 'react';

export type Route =
  | {view: 'today'} | {view: 'memory'} | {view: 'sources'}
  | {view: 'activity'; filter?: string}
  | {view: 'privacy'; tx?: string} | {view: 'case'; tx: string; from?: string};

export function parse(hash: string): Route {
  const [, view = 'today', id, from] = hash.replace(/^#/, '').split('/');
  const tx = id ? decodeURIComponent(id) : undefined;
  switch (view) {
    case 'memory': case 'sources': return {view};
    case 'activity': return {view, filter: tx};
    case 'privacy': return {view, tx};
    case 'case': return tx ? {view, tx, from} : {view: 'today'};
    default: return {view: 'today'};
  }
}
export const href = (route: Route) =>
  '#/' + route.view + ('tx' in route && route.tx ? '/' + encodeURIComponent(route.tx) : '')
  + (route.view === 'activity' && route.filter ? '/' + encodeURIComponent(route.filter) : '')
  + (route.view === 'case' && route.from ? '/' + route.from : '');

export function useRoute() {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => { setRoute(parse(window.location.hash)); window.scrollTo({top: 0}); };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
export const go = (route: Route) => { window.location.hash = href(route); };
