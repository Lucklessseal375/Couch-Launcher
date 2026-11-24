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
        // (up from the first row reaches the search bar, which sits well to the side)
        ways = ways.some(w => w.inline) ? ways.filter(w => w.inline) : ways.filter(w => w.off < (d[0] ? innerHeight / 3 : innerWidth * 0.6));
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
      if (ev.target.tagName === 'INPUT' || ev.target.closest('#couch-kb')) return;  // the search box and keyboard aren't places to come back to
      left[location.hash] ={i: [...document.querySelectorAll(FOCUSABLE)].indexOf(ev.target), sig: sig(ev.target)};
    }, true);
    const settle = () => {
      let tries = 0, stable = 0, shape = '';
      const old = document.activeElement;  // the item pressed on the page being left; it lingers a moment
      const t = setInterval(() => {
        const a = document.activeElement, m = left[location.hash];
        // something is selected, unless it's only the search box Stremio selects by itself, back on a page
        // where you had picked a result
        if (++tries > 30 || location.hash.startsWith('#/player') ||
            (a && a !== document.body && a !== old && a.isConnected && !(m && a.tagName === 'INPUT'))) return clearInterval(t);
        const every = [...document.querySelectorAll(FOCUSABLE)], all = every.filter(usable);
        let e = m && every[m.i] && sig(every[m.i]) === m.sig && usable(every[m.i]) ? every[m.i] : m && all.find(x => sig(x) === m.sig);
        if (!e) {
          // the page may still be filling in (sources arrive add-on by add-on): wait until it holds still
          const now = all.length + '|' + (all[0] ? sig(all[0]) : '');
          stable = now === shape ? stable + 1 : 0;
          shape = now;
          if (tries < 8 || (stable < 4 && tries < 30)) return;
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

  // An on-screen keyboard for text boxes (search), PS5-style: ✕ on a text box opens it (an empty search
  // page opens it by itself), the arrows move over the keys, ✕ types, □ deletes, ○ closes. It types into
  // Stremio's own box, so Stremio searches as if typed on a real keyboard.
  if (!window.couchKeyboard) {
    window.couchKeyboard = true;
    const ROWS = ['1234567890', 'qwertyuiop', "asdfghjkl'", 'zxcvbnm,.-'];
    const kcss = document.createElement('style');
    kcss.textContent = `
      #couch-kb { position: fixed; left: 50%; bottom: 4vh; transform: translateX(-50%); z-index: 2147483647;
        padding: 1.6rem 1.8rem 1.2rem; border-radius: 1.6rem; background: rgba(20, 16, 44, 0.9);
        backdrop-filter: blur(24px); box-shadow: 0 1.5rem 4rem rgba(0, 0, 0, 0.6); font-family: inherit;
        animation: couch-kb-in 180ms ease-out; }
      @keyframes couch-kb-in { from { opacity: 0; transform: translate(-50%, 2rem); } }
      #couch-kb .text { min-height: 2.6rem; margin: 0 0.3rem 1.1rem; padding: 0.5rem 1rem; border-radius: 0.8rem;
        background: rgba(255, 255, 255, 0.08); color: #fff; font-size: 1.7rem; white-space: pre; overflow: hidden; }
      #couch-kb .text::after { content: ''; display: inline-block; width: 2px; height: 1.6rem; margin-left: 2px;
        vertical-align: -0.2rem; background: #a58bff; animation: couch-kb-caret 1s steps(1) infinite; }
      @keyframes couch-kb-caret { 50% { opacity: 0; } }
      #couch-kb .row { display: flex; justify-content: center; gap: 0.5rem; margin-bottom: 0.5rem; }
      #couch-kb button { width: 4.4rem; height: 4.4rem; border: 0; border-radius: 0.9rem; font: inherit;
        font-size: 1.6rem; color: #fff; background: rgba(255, 255, 255, 0.1); outline: none;
        transition: transform 120ms ease-out, box-shadow 120ms ease-out, background 120ms; }
      #couch-kb button.wide { width: 14rem; font-size: 1.3rem; }
      #couch-kb button.go { background: #7b5bf5; }
      #couch-kb button:focus { background: rgba(165, 139, 255, 0.45); transform: scale(1.1);
        box-shadow: 0 0 1.4rem 0.25rem rgba(123, 91, 245, 0.85); }
      #couch-kb button.go:focus { background: #8f74ff; }
      #couch-kb .hint { margin-top: 0.7rem; text-align: center; color: rgba(255, 255, 255, 0.55); font-size: 1.1rem; }`;
    document.head.append(kcss);
    let kb = null, box = null;
    const setValue = v => {  // as typing would: React only notices an input event
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(box, v);
      box.dispatchEvent(new Event('input', {bubbles: true}));
      kb.querySelector('.text').textContent = v;
    };
    const close = () => {
      if (!kb) return;
      kb.remove();
      kb = null;
      box.focus({preventScroll: true});
    };
    const submit = () => {
      const b = box;
      close();
      b.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
      b.blur();  // the results get the selection
    };
    const press = k => {
      if (k === 'space') setValue(box.value + ' ');
      else if (k === 'delete') setValue(box.value.slice(0, -1));
      else if (k === 'search') submit();
      else setValue(box.value + k);
    };
    const open = input => {
      box = input;
      kb = document.createElement('div');
      kb.id = 'couch-kb';
      kb.setAttribute('role', 'dialog');  // the arrows stay inside it
      const text = document.createElement('div');
      text.className = 'text';
      text.textContent = input.value;
      kb.append(text);
      const key = (k, label, cls) => {
        const b = document.createElement('button');
        b.textContent = label;
        if (cls) b.className = cls;
        b.addEventListener('click', () => press(k));
        return b;
      };
      for (const r of [...ROWS.map(s => [...s].map(c => key(c, c))),
                       [key('space', 'Space', 'wide'), key('delete', '⌫', ''), key('search', 'Search', 'wide go')]]) {
        const row = document.createElement('div');
        row.className = 'row';
        row.append(...r);
        kb.append(row);
      }
      const hint = document.createElement('div');
      hint.className = 'hint';
      hint.textContent = '✕ type  ·  □ delete  ·  ○ close';
      hint.style.whiteSpace = 'pre';
      kb.append(hint);
      document.body.append(kb);
      kb.querySelectorAll('.row')[1].firstChild.focus({preventScroll: true});  // q
    };
    const isText = e => e && e.tagName === 'INPUT' && /^(text|search|)$/.test(e.type) || (e && e.tagName === 'TEXTAREA');
    addEventListener('keydown', ev => {
      if (!ev.isTrusted) return;  // our own Enter that submits the search
      if (kb) {
        if (ev.key === 'Backspace' || ev.key === 'Escape') close();  // ○
        else if (ev.key === ' ') press('delete');  // □
        else if (ev.key !== 'Enter' && !ev.key.startsWith('Arrow')) return;  // ✕ is Enter: the key's own click
        if (ev.key !== 'Enter' && !ev.key.startsWith('Arrow')) ev.preventDefault();
        if (!ev.key.startsWith('Arrow')) ev.stopImmediatePropagation();  // not Stremio's (Backspace is its back)
      } else if (ev.key === 'Enter' && isText(document.activeElement)) {
        ev.preventDefault();
        ev.stopImmediatePropagation();
        open(document.activeElement);
      }
    }, true);
    addEventListener('keyup', ev => { if (kb && ev.key === ' ') ev.preventDefault(); }, true);  // no click from □
    // an empty search page: straight to typing
    let was = '';
    setInterval(() => {
      if (location.hash === was) return;
      was = location.hash;
      if (was === '#/search') setTimeout(() => {
        const a = document.activeElement;
        if (!kb && location.hash === '#/search' && isText(a) && !a.value) open(a);
      }, 900);
    }, 150);
  }
  return true;
})()
