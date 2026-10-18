import {useEffect, useState} from 'react';

export type Route = (
  | {view: 'today'} | {view: 'activity'; filter?: string} | {view: 'memory'; lab?: string} | {view: 'sources'}
  | {view: 'admin'; tab?: string} | {view: 'fraudlab'; chapter?: string}
  | {view: 'privacy'; tx?: string; lab?: string} | {view: 'case'; tx: string; from?: string}
) & {customer?: string};

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/');
  const customer = parts[0] === 'sources' && /^customer_[0-9a-f]{32}$/.test(parts[1] ?? '')
    ? parts.splice(0, 2)[1] : undefined;
  const [view = 'today', id, from] = parts;
  let tx: string | undefined;
  try { tx = id ? decodeURIComponent(id) : undefined; }
  catch { return customer ? {view: 'today', customer} : {view: 'today'}; }
  let route: Route;
  switch (view) {
    case 'sources': route = {view}; break;
    case 'memory': route = id === 'lab' ? {view, lab: from ?? ''} : {view}; break;
    case 'activity': route = tx ? {view, filter: tx} : {view}; break;
    case 'admin': route = tx ? {view, tab: tx} : {view}; break;
    case 'fraud-lab': route = {view: 'fraudlab', chapter: tx}; break;
    case 'privacy': route = id === 'lab' ? {view, lab: from ?? ''} : {view, tx}; break;
    case 'case': route = tx ? {view, tx, from} : {view: 'today'}; break;
    default: route = {view: 'today'};
  }
  return customer ? {...route, customer} : route;
}
export const href = (route: Route) => {
  let path = route.view === 'fraudlab' ? 'fraud-lab' + (route.chapter ? '/' + encodeURIComponent(route.chapter) : '') : route.view;
  if ((route.view === 'memory' || route.view === 'privacy') && route.lab !== undefined) path += '/lab' + (route.lab ? '/' + encodeURIComponent(route.lab) : '');
  else if ('tx' in route && route.tx) path += '/' + encodeURIComponent(route.tx);
  if (route.view === 'activity' && route.filter) path += '/' + encodeURIComponent(route.filter);
  if (route.view === 'admin' && route.tab) path += '/' + encodeURIComponent(route.tab);
  if (route.view === 'case' && route.from) path += '/' + route.from;
  return '#/' + (route.customer && route.view !== 'sources' ? 'sources/' + encodeURIComponent(route.customer) + '/' : '') + path;
};

export function useRoute() {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash)); window.scrollTo({top: 0});
      document.getElementById('main')?.scrollTo({top: 0});
      document.getElementById('V-CUSTOMERS')?.scrollTo({top: 0});
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
export const go = (route: Route) => { window.location.hash = href(route); };
