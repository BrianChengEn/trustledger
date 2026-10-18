import {useEffect, useRef, useState} from 'react';
import {Icon} from './icons';

/**
 * Page buttons for a clipped region (the element right before this one). Nothing in the app is user-scrollable, so long
 * data is shown a page at a time. Rows stay in the DOM; only the visible window moves.
 */
export default function Pager() {
  const mark = useRef<HTMLDivElement>(null);
  const [state, setState] = useState({page: 0, pages: 1});
  const region = () => mark.current?.previousElementSibling as HTMLElement | null;
  useEffect(() => {
    const parent = mark.current?.parentElement;
    if (!parent) return;
    // Always measure whichever element currently sits before the buttons (the table or the JSON view can be swapped).
    const measure = () => {
      const el = region();
      if (!el) return;
      el.setAttribute('data-paged', ''); // the scroll lock leaves this region to the page buttons
      const step = Math.max(1, el.clientHeight);
      const pages = Math.max(1, Math.ceil((el.scrollHeight - 2) / step));
      const page = el.scrollTop >= el.scrollHeight - step - 1 ? pages - 1 : Math.round(el.scrollTop / step);
      setState({pages, page: Math.min(pages - 1, page)});
    };
    measure();
    // The region may not have its final size on the first frame (flex layout, entrance animation), so measure again.
    const later = [window.setTimeout(measure, 120), window.setTimeout(measure, 600)];
    const resize = new ResizeObserver(measure), mutate = new MutationObserver(measure);
    resize.observe(parent); mutate.observe(parent, {childList: true, subtree: true});
    parent.addEventListener('scroll', measure, true);
    return () => { later.forEach(window.clearTimeout); resize.disconnect(); mutate.disconnect(); parent.removeEventListener('scroll', measure, true); };
  }, []);
  const to = (page: number) => { const el = region(); if (el) el.scrollTo({top: page * el.clientHeight, behavior: 'smooth'}); };
  return <div className="pager" ref={mark} hidden={state.pages < 2} role="group" aria-label="Pages">
    <button className="iconbtn" aria-label="Previous page" disabled={state.page === 0} onClick={() => to(state.page - 1)}><Icon name="chevronUp" size={15}/></button>
    <span>{state.page + 1} / {state.pages}</span>
    <button className="iconbtn" aria-label="Next page" disabled={state.page >= state.pages - 1} onClick={() => to(state.page + 1)}><Icon name="chevronDown" size={15}/></button>
  </div>;
}

/** Explicit page buttons for a list that shows a fixed number of items per page (nothing scrolls). */
export function PageNav({page, pages, onPage}: {page: number; pages: number; onPage: (page: number) => void}) {
  return <div className="pager" hidden={pages < 2} role="group" aria-label="Pages">
    <button className="iconbtn" aria-label="Previous page" disabled={page === 0} onClick={() => onPage(page - 1)}><Icon name="chevronUp" size={15}/></button>
    <span>{page + 1} / {pages}</span>
    <button className="iconbtn" aria-label="Next page" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}><Icon name="chevronDown" size={15}/></button>
  </div>;
}
