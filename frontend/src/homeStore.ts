import {useSyncExternalStore} from 'react';
import type {IconName} from './icons';

/** Home-screen widgets (iPhone style). The grid is 4 wide and 2 tall, so at most 8 cells. */
export const WIDGET_CELLS = 8;
const STORAGE = 'trustledger.home.widgets.v2';

export interface WidgetDef {id: string; name: string; size: 1 | 2; icon: IconName; blurb: string}
export const WIDGETS: WidgetDef[] = [
  {id: 'spending', name: 'Spending', size: 2, icon: 'wallet', blurb: 'Sample spending at a glance'},
  {id: 'status', name: 'System status', size: 2, icon: 'activity', blurb: 'Data, analysis and memory'},
  {id: 'alerts', name: 'Alerts', size: 2, icon: 'bell', blurb: 'Open alerts and what is next'},
  {id: 'privacy', name: 'Privacy', size: 1, icon: 'lock', blurb: 'What is removed before AI'},
  {id: 'memory', name: 'Memory', size: 1, icon: 'hardDrive', blurb: 'Preferences you chose to keep'},
  {id: 'recurring', name: 'Subscriptions', size: 1, icon: 'repeat', blurb: 'Recurring charges'},
  {id: 'largest', name: 'Largest charge', size: 1, icon: 'trendingUp', blurb: 'The biggest purchase'},
  {id: 'nessie', name: 'Nessie', size: 1, icon: 'database', blurb: 'Open the sandbox console'},
];
export const DEFAULT_WIDGETS = ['spending', 'privacy', 'memory', 'recurring', 'largest', 'status'];

const sizeOf = (id: string) => WIDGETS.find(w => w.id === id)?.size ?? 1;
export const cellsUsed = (ids: string[]) => ids.reduce((n, id) => n + sizeOf(id), 0);

function load(): string[] {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE) ?? 'null');
    if (Array.isArray(stored)) {
      const ids: string[] = [];
      for (const id of stored) if (typeof id === 'string' && WIDGETS.some(w => w.id === id) && !ids.includes(id)
        && cellsUsed([...ids, id]) <= WIDGET_CELLS) ids.push(id);
      return ids;
    }
  } catch { /* storage unavailable or malformed: use the defaults */ }
  return DEFAULT_WIDGETS;
}

interface State {ids: string[]; editing: boolean; gallery: boolean}
let state: State = {ids: load(), editing: false, gallery: false};
const listeners = new Set<() => void>();
function set(next: Partial<State>) {
  state = {...state, ...next};
  if (next.ids) { try { window.localStorage.setItem(STORAGE, JSON.stringify(state.ids)); } catch { /* layout just won't persist */ } }
  listeners.forEach(l => l());
}

export const widgetStore = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  snapshot: () => state,
  setEditing: (editing: boolean) => set({editing, gallery: editing ? state.gallery : false}),
  setGallery: (gallery: boolean) => set({gallery}),
  add: (id: string) => { if (!state.ids.includes(id) && cellsUsed([...state.ids, id]) <= WIDGET_CELLS) set({ids: [...state.ids, id], gallery: false}); },
  remove: (id: string) => set({ids: state.ids.filter(x => x !== id)}),
  move(id: string, step: -1 | 1) {
    const from = state.ids.indexOf(id), to = from + step;
    if (from < 0 || to < 0 || to >= state.ids.length) return;
    const ids = [...state.ids]; [ids[from], ids[to]] = [ids[to], ids[from]];
    set({ids});
  },
  reset: () => set({ids: DEFAULT_WIDGETS, gallery: false}),
};
export const useWidgets = () => useSyncExternalStore(widgetStore.subscribe, widgetStore.snapshot);
