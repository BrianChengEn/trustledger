/**
 * Nothing in the desktop UI is user-scrollable. CSS clips every container (overflow: hidden); this is the second layer.
 * It swallows wheel and trackpad scrolling, and undoes any scroll the browser performs on its own (focusing an element,
 * find-in-page, drag-selecting, anchors). Regions marked data-paged are moved only by their own page buttons.
 * Touch phones are excluded: their flowing layout has to scroll.
 */
const locked = () => document.documentElement.dataset.stage === 'on';

window.addEventListener('wheel', event => { if (locked()) event.preventDefault(); }, {passive: false, capture: true});
window.addEventListener('touchmove', event => { if (locked()) event.preventDefault(); }, {passive: false, capture: true});

function undo(target: EventTarget | null) {
  if (!locked()) return;
  if (target === document || target === window || target === document.documentElement || target === document.body) {
    if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0; document.documentElement.scrollLeft = 0;
    document.body.scrollTop = 0; document.body.scrollLeft = 0;
    return;
  }
  if (target instanceof HTMLElement && !target.hasAttribute('data-paged') && (target.scrollTop || target.scrollLeft)) {
    target.scrollTop = 0; target.scrollLeft = 0;
  }
}
document.addEventListener('scroll', event => undo(event.target), true);
window.addEventListener('scroll', () => undo(document), true);
