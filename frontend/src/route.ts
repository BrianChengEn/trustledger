import {useEffect, useState} from 'react';

export type Route = (
  | {view: 'today'} | {view: 'activity'; filter?: string} | {view: 'memory'} | {view: 'sources'}
  | {view: 'privacy'; tx?: string} | {view: 'case'; tx: string; from?: string}
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
    case 'memory': case 'sources': route = {view}; break;
    case 'activity': route = tx ? {view, filter: tx} : {view}; break;
    case 'privacy': route = {view, tx}; break;
    case 'case': route = tx ? {view, tx, from} : {view: 'today'}; break;
    default: route = {view: 'today'};
  }
  return customer ? {...route, customer} : route;
}
export const href = (route: Route) =>
  '#/' + (route.customer && route.view !== 'sources' ? 'sources/' + encodeURIComponent(route.customer) + '/' : '')
  + route.view + ('tx' in route && route.tx ? '/' + encodeURIComponent(route.tx) : '')
  + (route.view === 'activity' && route.filter ? '/' + encodeURIComponent(route.filter) : '')
  + (route.view === 'case' && route.from ? '/' + route.from : '');

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
