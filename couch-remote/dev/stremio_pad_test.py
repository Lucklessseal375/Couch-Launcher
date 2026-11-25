"""Stremio through Couch's real controller loop, fed by an SDL virtual gamepad: full screen, pointer, held
d-pad, side menu, title pages, back, and the Board's back closing Stremio. Opens Stremio from Couch on the TV.

    python dev/stremio_pad_test.py
"""
import ctypes, json, os, re, subprocess, sys, threading, time, urllib.request
COUCH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [COUCH, COUCH + r"\dev"]
os.chdir(COUCH)
import server
from shoot import WS
server.log.disabled = True  # this test copy must not write into the real server.log
u = ctypes.windll.user32

# Stremio, opened by Couch itself (its launch request), watched on the DevTools port Couch gives it
req = urllib.request.Request("http://127.0.0.1:8765/api/launch", data=b'{"id": "stremio"}', method="POST",
                             headers={"X-Couch": "1", "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read())
for _ in range(60):
    time.sleep(0.5)
    try:
        pages = [p for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{server.app_devtools_port()}/json")) if p["type"] == "page" and "stremio" in p["url"]]
        if pages: break
    except Exception: pass
time.sleep(5)
h = u.FindWindowW(None, "Stremio")
ws = WS(pages[0]["webSocketDebuggerUrl"])
ev = lambda e: ws.send("Runtime.evaluate", expression=e, returnByValue=True)["result"].get("value")
ACT = "(()=>{const a=document.activeElement; return a.tagName+' '+(a.getAttribute('aria-label')||a.title||a.textContent||'').slice(0,30)})()"

threading.Thread(target=server._controller_loop, daemon=True).start()
time.sleep(3)
import pygame
sdl = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__), "SDL2.dll"))
sdl.SDL_JoystickOpen.restype = ctypes.c_void_p
sdl.SDL_JoystickSetVirtualButton.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8)
sdl.SDL_JoystickSetVirtualAxis.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int16)
idx = sdl.SDL_JoystickAttachVirtual(1, 6, 15, 0)  # a game controller: 6 axes, 15 buttons
joy = sdl.SDL_JoystickOpen(idx)
print("virtual pad", idx, bool(joy))
time.sleep(4)  # past the 3 s after a connect

A, B, X, UP, DOWN, LEFT, RIGHT = 0, 1, 2, 11, 12, 13, 14
def btn(b, wait=0.8):
    sdl.SDL_JoystickSetVirtualButton(joy, b, 1); time.sleep(0.12)
    sdl.SDL_JoystickSetVirtualButton(joy, b, 0); time.sleep(wait)

results = []
import re
is_home = lambda hsh: bool(re.search(r"#/($|\?)", hsh))
def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name, detail)

home = ev("location.hash")
check("Stremio in front", u.GetForegroundWindow() == h)
hover = ev("(()=>{const h=[...document.querySelectorAll(':hover')].pop(); return h ? (h.closest('a,[title]') ? 'POSTER ' : '')+h.tagName+'.'+h.className : 'nothing'})()")
import ctypes.wintypes as wt; pt = wt.POINT(); u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4)); u.GetCursorPos(ctypes.byref(pt))
check("pointer parked in the corner, over no poster", pt.x >= 4090 and pt.y >= 2150 and not hover.startswith("POSTER"), f"{pt.x},{pt.y} hover={hover!r}")
ev("window.__sc=[...document.querySelectorAll('*')].find(e=>e.scrollHeight>e.clientHeight+50 && /auto|scroll/.test(getComputedStyle(e).overflowY)); 0")
btn(DOWN, 0.5)
top0 = ev("__sc.scrollTop")
sdl.SDL_JoystickSetVirtualButton(joy, DOWN, 1); time.sleep(2.0); sdl.SDL_JoystickSetVirtualButton(joy, DOWN, 0); time.sleep(0.5)
top1 = ev("__sc.scrollTop")
rows = round((top1 - top0) / 370)
check("holding down for 2 s scrolls far (old pace: ~15 rows)", rows >= 25, f"{rows} rows ({top0:.0f} -> {top1:.0f})")
sdl.SDL_JoystickSetVirtualButton(joy, UP, 1); time.sleep(2.0); sdl.SDL_JoystickSetVirtualButton(joy, UP, 0); time.sleep(0.8)
top2 = ev("__sc.scrollTop")
check("holding up climbs back through rows off screen", top2 < top1 - 25 * 370 * 0.8, f"{top1:.0f} -> {top2:.0f}")
btn(LEFT); btn(LEFT); btn(LEFT); btn(LEFT); btn(LEFT); btn(LEFT); btn(LEFT); btn(LEFT)
menu = ev(ACT)
check("left reaches the side menu", "Board" in menu or "Discover" in menu or "Library" in menu or "Calendar" in menu or "Addons" in menu or "Settings" in menu, menu)
btn(RIGHT)
check("right comes back to the posters", ev("document.activeElement.className").startswith("meta-item-link"), ev(ACT))
a0 = ev(ACT); btn(DOWN); a1 = ev(ACT); btn(RIGHT); a2 = ev(ACT)
check("d-pad moves the selection", len({a0, a1, a2}) == 3, f"{a0} -> {a1} -> {a2}")
sdl.SDL_JoystickSetVirtualAxis(joy, 0, 32767); time.sleep(0.25); sdl.SDL_JoystickSetVirtualAxis(joy, 0, 0); time.sleep(0.8)
a3 = ev(ACT)
check("left stick moves the selection", a3 != a2, f"{a2} -> {a3}")
btn(A, 2.5)
check("a title page opens with something selected", ev("document.activeElement !== document.body"), ev(ACT))
btn(B, 2.0)
check("back on the Board, the poster you opened is selected again", ev(ACT) == a3, f"{a3} vs {ev(ACT)}")
btn(A, 2.5)
detail = ev("location.hash")
check("A opens the title", detail != home and "detail" in detail, detail)
btn(X, 1.5)
check("X does no harm on a title page", u.IsWindow(h) and ev("location.hash") == detail)
btn(B, 2.5)
after = ev("location.hash")
check("B on a title page goes back, Stremio stays open", u.IsWindow(h) and after != detail, after)
for _ in range(3):  # back until the Board
    if is_home(ev("location.hash")): break
    btn(B, 2.5)
check("B reaches the Board", is_home(ev("location.hash")) and u.IsWindow(h), ev("location.hash"))
btn(B, 3.5)
gone = not u.IsWindow(h) or not u.IsWindowVisible(h)
check("B on the first screen closes Stremio", gone)
fg = u.GetForegroundWindow()
check("Couch comes back in front", server.window_exe(fg) == "msedge.exe" and fg == server.find_launcher(), server.window_exe(fg))
sdl.SDL_JoystickDetachVirtual(idx)
print("ALL PASS" if all(results) else "SOME FAILED")
os._exit(0)
