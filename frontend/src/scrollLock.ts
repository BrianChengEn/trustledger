/**
 * The page itself never scrolls. CSS clips every layout container (overflow: hidden); this is the second layer.
 * Only a box that is deliberately scrollable (overflow-y: auto, e.g. a long list or a long result) scrolls, and only
 * inside itself. Everything else swallows wheel and trackpad scrolling, and undoes any scroll the browser performs on
 * its own (focusing an element, find-in-page, drag-selecting, anchors).
 * Touch phones are excluded: their flowing layout has to scroll.
 */
const locked = () => document.documentElement.dataset.stage === 'on';

/** The nearest box under the pointer that can really scroll vertically (and not past its edge), if any. */
function scroller(start: EventTarget | null, dy: number): HTMLElement | null {
  for (let el = start instanceof Element ? start : null; el && el !== document.documentElement; el = el.parentElement) {
    if (!(el instanceof HTMLElement)) continue;
    const style = getComputedStyle(el);
    if (!/(auto|scroll)/.test(style.overflowY) || el.scrollHeight <= el.clientHeight + 1) continue;
    const atTop = el.scrollTop <= 0, atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
    if ((dy < 0 && !atTop) || (dy > 0 && !atBottom) || dy === 0) return el;
  }
  return null;
}

window.addEventListener('wheel', event => {
  if (!locked()) return;
  // Sideways or diagonal gestures never move anything; vertical ones may move the box under the pointer.
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY) || !scroller(event.target, event.deltaY)) event.preventDefault();
}, {passive: false, capture: true});
let lastY = 0;
window.addEventListener('touchstart', event => { lastY = event.touches[0]?.clientY ?? 0; }, {passive: true, capture: true});
window.addEventListener('touchmove', event => {
  if (!locked()) return;
  const y = event.touches[0]?.clientY ?? lastY, dy = lastY - y; lastY = y;
  if (!scroller(event.target, dy)) event.preventDefault();
}, {passive: false, capture: true});

function undo(target: EventTarget | null) {
  if (!locked()) return;
  if (target === document || target === window || target === document.documentElement || target === document.body) {
    if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0; document.documentElement.scrollLeft = 0;
    document.body.scrollTop = 0; document.body.scrollLeft = 0;
    return;
  }
  if (!(target instanceof HTMLElement)) return;
  if (target.scrollLeft) target.scrollLeft = 0;
  // A deliberately scrollable box keeps its vertical position; any other container snaps back.
  if (target.scrollTop && !/(auto|scroll)/.test(getComputedStyle(target).overflowY)) target.scrollTop = 0;
}
document.addEventListener('scroll', event => undo(event.target), true);
window.addEventListener('scroll', () => undo(document), true);
