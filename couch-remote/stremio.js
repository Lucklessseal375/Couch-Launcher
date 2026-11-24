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
  // Arrow keys move the selection to the nearest item that way anywhere on the page, as on a TV, and the
  // page glides to keep it in the middle. Stremio's own arrows only reach items already on screen: Up
  // stalled once the row above had scrolled away, and the side menu and search were out of reach.
  // Its video player keeps its arrows (seek, volume); a text box keeps left and right for its caret.
  if (!window.couchNav) {
    window.couchNav = true;
    const DIRS = {ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0]};
    // not the invisible file drop zone that covers the page (Enter there opens a file picker)
    const FOCUSABLE = 'a[href], button, input:not([type=file]), textarea, select, [tabindex]:not([tabindex="-1"])';
    const LAYER = '[role=dialog], [role=menu], [class*=modal-container], [class*=menu-container]';  // open menus keep the selection in
    const usable = e => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.left >= -2 && r.right <= innerWidth + 2 && !e.disabled &&
        getComputedStyle(e).visibility !== 'hidden' && !e.closest('[aria-hidden=true]');
    };
    addEventListener('keydown', ev => {
      const d = DIRS[ev.key];
      if (!d || ev.altKey || ev.ctrlKey || location.hash.startsWith('#/player')) return;
      const a = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
      if (a && d[0] && /^(INPUT|TEXTAREA)$/.test(a.tagName)) return;
      const all = [...((a && a.closest(LAYER)) || document).querySelectorAll(FOCUSABLE)].filter(e => e !== a && usable(e));
      let next;
      if (!a) {  // nothing selected yet: the first title
        next = all.find(e => e.matches('[class*=meta-item-link]')) || all[0];
      } else {
        const r = a.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        let ways = all.map(e => {
          const c = e.getBoundingClientRect();
          const gap = d[0] > 0 ? c.left - r.right : d[0] < 0 ? r.left - c.right : d[1] > 0 ? c.top - r.bottom : r.top - c.bottom;
          const off = d[0] ? Math.abs(c.top + c.height / 2 - cy) : Math.abs(c.left + c.width / 2 - cx);
          // in line: shares some height (moving sideways) or width (moving up or down) with the current item
          const inline = d[0] ? c.top < r.bottom && c.bottom > r.top : c.left < r.right && c.right > r.left;
          return {e, gap, off, inline};
        }).filter(w => w.gap >= -4);  // wholly on that side
        // stay in this row or column if anything that way is in it, else the nearest item not far out of line
        ways = ways.some(w => w.inline) ? ways.filter(w => w.inline) : ways.filter(w => w.off < (d[0] ? innerHeight : innerWidth) / 3);
        if (ways.length) {  // the nearest row or column that way, then the item in it most in line
          const band = Math.min(...ways.map(w => w.gap)) + (d[0] ? r.width : r.height) / 2;
          next = ways.filter(w => w.gap <= band).sort((p, q) => p.off - q.off || p.gap - q.gap)[0].e;
        }
      }
      ev.preventDefault();
      ev.stopImmediatePropagation();
      if (!next) {  // nothing that way: up and down glide the page (long text), sideways stays put
        let s = a && a.parentElement;
        while (s && !(s.scrollHeight > s.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(s).overflowY))) s = s.parentElement;
        if (d[1]) (s || document.scrollingElement).scrollBy({top: d[1] * innerHeight * 0.4, behavior: 'smooth'});
        return;
      }
      next.focus({preventScroll: true});
      // a single press glides; a held direction (moves under 150 ms apart) keeps up instead of trailing
      const now = performance.now(), held = now - (window.couchLastMove || 0) < 150;
      window.couchLastMove = now;
      next.scrollIntoView({behavior: held ? 'instant' : 'smooth', block: 'center', inline: 'nearest'});
    }, true);

    // Every page starts with something selected: back on a page, the item you left it from (back from a
    // title, the poster you opened); on a new one, its first item. Stremio selects nothing after a move.
    const sig = e => (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 60);
    const left = {};  // page address: the selected item there, by position and label
    addEventListener('focusin', ev => {
      left[location.hash] = {i: [...document.querySelectorAll(FOCUSABLE)].indexOf(ev.target), sig: sig(ev.target)};
    }, true);
    const settle = () => {
      let tries = 0;
      const old = document.activeElement;  // the item pressed on the page being left; it lingers a moment
      const t = setInterval(() => {
        const a = document.activeElement;
        if (++tries > 30 || location.hash.startsWith('#/player') ||
            (a && a !== document.body && a !== old && a.isConnected)) return clearInterval(t);  // something is selected
        const every = [...document.querySelectorAll(FOCUSABLE)], all = every.filter(usable);
        const m = left[location.hash];
        let e = m && every[m.i] && sig(every[m.i]) === m.sig && usable(every[m.i]) ? every[m.i] : m && all.find(x => sig(x) === m.sig);
        if (!e) {
          if (tries < 8) return;  // the page may still be filling in
          // the first poster, episode or source in reading order (not a link out to a website, which opens a
          // browser), else the first item past the side menu and header
          const box = x => x.getBoundingClientRect();
          const main = all.filter(x => box(x).left > 90 && box(x).top > 70).sort((p, q) => box(p).top - box(q).top || box(p).left - box(q).left);
          e = main.find(x => x.matches('[class*=meta-item-link], [class*=label-container]:not([href^=http])')) || main[0];
        }
        if (!e) return;
        clearInterval(t);
        e.focus({preventScroll: true});
        e.scrollIntoView({block: 'center', inline: 'nearest'});
      }, 100);
    };
    let page = location.hash;  // Stremio opens pages with pushState, which fires no event: watch the address
    setInterval(() => { if (location.hash !== page) { page = location.hash; settle(); } }, 150);
    settle();
  }
  return true;
})()
