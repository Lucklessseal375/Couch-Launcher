// Couch runs this in Stremio's page (apps.json "page_script") every half second until it returns true.
(() => {
  if (!window.core || !document.querySelector('[class*=board-row]')) return false;  // not loaded yet
  // Stremio loads a Board row only once scrolling rests for 0.3 s, so a held d-pad stopped at the last
  // loaded row. Load them all now.
  core.dispatch({action: 'CatalogsWithExtra', args: {action: 'LoadRange', args: {start: 0, end: 1000}}}, 'board');
  // The selection as a soft glow and a lift, as in Couch, instead of Stremio's white ring and outlines.
  // Class names are matched by prefix: Stremio adds a hash to each.
  const css = document.createElement('style');
  css.textContent = `
    [class*=poster-container] { transition: transform 150ms ease-out, box-shadow 150ms ease-out; }
    [class*=meta-item-container]:focus-within [class*=poster-container] {
      box-shadow: 0 0.5rem 2.2rem 0.3rem rgba(123, 91, 245, 0.8) !important;
      transform: scale(1.06);
    }
    [class*=button-container]:not([class*=meta-item-link]):focus,
    [class*=button-container]:not([class*=meta-item-link]):focus-visible {
      outline: none !important;
      box-shadow: 0 0 1.4rem 0.25rem rgba(123, 91, 245, 0.85) !important;
    }`;
  document.head.append(css);
  // Selected by keys, an item with a title shows it in a white-bordered box under it; the title is
  // already printed there. Strip titles, including the ones Stremio adds or sets again later.
  const untitle = n => {
    if (n.removeAttribute) n.removeAttribute('title');
    if (n.querySelectorAll) n.querySelectorAll('[title]').forEach(e => e.removeAttribute('title'));
  };
  untitle(document.body);
  new MutationObserver(ms => ms.forEach(m => m.type === 'attributes' ? untitle(m.target) : m.addedNodes.forEach(untitle)))
    .observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['title']});
  return true;
})()
