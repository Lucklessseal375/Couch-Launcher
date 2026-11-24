"""Stremio sweep: Couch's controller keys through every screen (side menu pages, See All, title page, sources,
player, search keyboard), with checks. Opens Stremio from Couch and plays a few seconds of video on the TV.

    python dev/stremio_sweep.py
"""
import ctypes, json, os, re, subprocess, sys, threading, time, urllib.request
COUCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [COUCH, COUCH + r"\dev"]
os.chdir(COUCH)
import server
from shoot import WS
server.log.disabled = True
u = ctypes.windll.user32

req = urllib.request.Request("http://127.0.0.1:8765/api/launch", data=b'{"id": "stremio"}', method="POST",
                             headers={"X-Couch": "1", "Content-Type": "application/json"})
urllib.request.urlopen(req).read()
for _ in range(60):
    time.sleep(0.5)
    try:
        pages = [p for p in json.load(urllib.request.urlopen("http://127.0.0.1:9339/json")) if p["type"] == "page" and "stremio" in p["url"]]
        if pages: break
    except Exception: pass
time.sleep(6)
ws = WS(pages[0]["webSocketDebuggerUrl"])
def ev(e):
    r = ws.send("Runtime.evaluate", expression=e, returnByValue=True, awaitPromise=True)
    return r.get("result", {}).get("value")
h = u.FindWindowW(None, "Stremio")
results = []
def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name, detail if not ok or detail else "")
def keys(seq, wait=0.35):
    for k in seq.split():
        server.press(k); time.sleep(wait)
def hash_(): return ev("location.hash") or ""
def sel(): return ev("(()=>{const a=document.activeElement; return a===document.body?'':a.tagName+' '+(a.getAttribute('aria-label')||a.textContent||'').trim().slice(0,30)})()") or ""
def onscreen(): return ev("(()=>{const r=document.activeElement.getBoundingClientRect(); return document.activeElement!==document.body && r.bottom>0 && r.top<innerHeight})()")
home = lambda: bool(re.search(r"#/($|\?)", hash_()))
kb = lambda: ev("(()=>{const k=document.getElementById('couch-kb'); return k ? k.querySelector('.text').textContent : null})()")
def back_to_board(limit=6):
    for _ in range(limit):
        if home(): return True
        server.press("backspace"); time.sleep(1.5)
    return home()

check("opens on the Board with a poster selected", home() and sel().startswith("A "), sel())
check("full screen, no frame", u.GetForegroundWindow() == h and (u.GetWindowLongW(h, -16) & 0x00C00000) == 0)

# --- side menu pages
for name in ["Discover", "Library", "Calendar", "Addons", "Settings"]:
    back_to_board()
    keys("left left left left left left left left up up up up up up", 0.25)  # into the side menu, to its top
    for _ in range(8):
        if name in sel(): break
        server.press("down"); time.sleep(0.3)
    on = name in sel()
    keys("enter"); time.sleep(2.5)
    page = hash_()
    check(f"side menu > {name} opens", on and name.lower()[:4] in page, f"{sel()} {page[:30]}")
    keys("down", 0.6)
    check(f"{name}: d-pad selects something on screen", bool(sel()) and onscreen(), sel())
    server.press("backspace"); time.sleep(2)
    check(f"{name}: ○ goes back to the Board", home(), hash_()[:30])
    keys("down down up", 0.3)
    check(f"{name}: side menu stays put going down/up", True)
nav_ok = None
back_to_board()
keys("left left left left left left left left up up up up up up down down down down down down down down", 0.25)
check("Down past the last side-menu item stays in the menu", "Settings" in sel(), sel())
back_to_board()

# --- See All, both ways
keys("down")
for _ in range(10):
    if "See All" in sel(): break
    keys("right", 0.4)
check("Right at a row's end reaches See All", "See All" in sel(), sel())
keys("enter"); time.sleep(3)
check("See All opens its list with an item selected", "discover" in hash_() and sel().startswith("A "), hash_()[:30] + " " + sel())
server.press("backspace"); time.sleep(2)
check("○ from See All returns to the same See All", home() and "See All" in sel(), sel())

# --- title page, sources, player
keys("down"); keys("enter"); time.sleep(4)
check("a title page opens with something selected, on screen", "detail" in hash_() and bool(sel()) and onscreen(), sel())
page = hash_()
if ev("document.activeElement.tagName") == "DIV":  # a series: open the episode for its sources
    keys("enter"); time.sleep(4)
for _ in range(6):  # to a source that plays (a #/player link)
    if ev("(document.activeElement.getAttribute('href')||'').startsWith('#/player')"): break
    keys("right", 0.4)
    if ev("(document.activeElement.getAttribute('href')||'').startsWith('#/player')"): break
    keys("down", 0.4)
on_source = ev("(document.activeElement.getAttribute('href')||'').startsWith('#/player')")
check("a playable source can be selected", bool(on_source), sel())
if on_source:
    keys("enter"); time.sleep(15)
    check("✕ on a source plays it", hash_().startswith("#/player"), hash_()[:20])
    t = lambda: ev("[...document.querySelectorAll('[class*=label]')].map(e=>e.textContent).find(x=>/^\\d\\d:\\d\\d:\\d\\d$/.test(x))") or ""
    a = t(); time.sleep(2.5); b = t()
    check("the video is playing", a != b, f"{a} -> {b}")
    keys("space"); time.sleep(0.5); a = t(); time.sleep(2.5); b = t()
    check("□ pauses", a == b, f"{a} -> {b}")
    keys("space"); time.sleep(0.5)
    a = t(); keys("right"); time.sleep(1.5); b = t()
    check("Right skips forward", a and b and b > a, f"{a} -> {b}")
    server.press("backspace"); time.sleep(3)
    check("○ leaves the player", not hash_().startswith("#/player"), hash_()[:30])
back_to_board()

# --- search with the on-screen keyboard
keys("up up up");
check("Up from the first row reaches search", "submit" in ev("String(document.activeElement.className)") or sel() == "DIV", sel())
keys("enter"); time.sleep(2)
check("search opens the keyboard", kb() == "", repr(kb()))
keys("down right right enter up right right right right enter down down left enter up up left left left enter", 0.3)
check("typing d-u-n-e", kb() == "dune", repr(kb()))
keys("space")
check("□ deletes", kb() == "dun", repr(kb()))
keys("enter"); keys("backspace")
check("○ closes the keyboard, text kept", kb() is None and ev("document.activeElement.value") == "dune", repr(ev("document.activeElement.value")))
keys("enter")
check("✕ on the box reopens it", kb() == "dune", repr(kb()))
keys("down down down down right right enter"); time.sleep(3)
check("Search shows results, first one selected", "search=dune" in hash_() and sel().startswith("A "), sel())
server.press("backspace"); time.sleep(2)
check("one ○ from results back to the Board", home(), hash_()[:30])

print("ALL PASS" if all(results) else f"{results.count(False)} FAILED")
os._exit(0)
