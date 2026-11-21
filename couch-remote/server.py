"""Couch Remote: a controller-friendly launcher on the TV plus a phone remote.

Run:  python server.py --open   (the Couch Launcher shortcut does this with the window hidden)
      python server.py          (just the server, with a console, for debugging)

Needs Python 3 and pygame (python -m pip install pygame) for the controller. Windows only.
"""
import ctypes
import ipaddress
import json
import logging
import logging.handlers
import os
import re
import socket
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
CONFIG_FILE = ROOT / "config.json"
APPS_FILE = ROOT / "apps.json"
CHOICES_FILE = ROOT / "choices.json"  # games hidden or pinned with the launcher's □ button
PROFILES = ROOT / "profiles"
LAUNCHER_TITLE = "Couch Launcher"
TV_USER_AGENT = ("Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) 76.0.3809.146/6.0 TV Safari/537.36")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.handlers.RotatingFileHandler(ROOT / "server.log", maxBytes=1_000_000,
                                                                   backupCount=1, encoding="utf-8")])
log = logging.getLogger("couch")


# ---------------------------------------------------------------- config

def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except ValueError:
            cfg = {}
    changed = False
    if cfg.pop("pin", None) is not None:
        changed = True
    if "port" not in cfg:
        cfg["port"] = 8765
        changed = True
    if "edge" not in cfg:
        for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if os.path.exists(p):
                cfg["edge"] = p
                break
        changed = True
    if changed:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


CONFIG = load_config()


def load_apps():
    data = json.loads(APPS_FILE.read_text(encoding="utf-8"))
    return data.get("apps", []), set(int(x) for x in data.get("hide_steam_apps", []))


def load_games():
    """Non-Steam games from apps.json (e.g. Epic), shown first in the Games row."""
    return json.loads(APPS_FILE.read_text(encoding="utf-8")).get("games", [])


# ---------------------------------------------------------------- Steam library

def steam_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return Path(r"C:\Program Files (x86)\Steam")


def parse_vdf(text):
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', text)
    unescape = lambda s: s.replace("\\\\", "\\").replace('\\"', '"')

    def parse(i):
        out = {}
        while i < len(tokens):
            s, brace = tokens[i]
            if brace == "}":
                return out, i + 1
            if brace == "{":  # malformed; skip
                i += 1
                continue
            key = unescape(s)
            i += 1
            if i >= len(tokens):
                break
            s2, b2 = tokens[i]
            if b2 == "{":
                val, i = parse(i + 1)
            else:
                val, i = unescape(s2), i + 1
            out[key] = val
        return out, i

    return parse(0)[0]


TOOL_NAME = re.compile(r"redistributable|proton|steamvr|steamworks|steam linux runtime|dedicated server", re.I)


def steam_games():
    _, hidden = load_apps()
    root = steam_path()
    libs = [root]
    try:
        lf = parse_vdf((root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace"))
        for v in lf.get("libraryfolders", {}).values():
            if isinstance(v, dict) and v.get("path"):
                libs.append(Path(v["path"]))
    except OSError:
        pass
    games, seen = [], set()
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                st = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
                appid = int(st.get("appid", 0))
            except (OSError, ValueError):
                continue
            name = st.get("name", "")
            if not appid or appid in seen or appid in hidden or TOOL_NAME.search(name):
                continue
            if not int(st.get("StateFlags", "0") or 0) & 4:  # not fully installed
                continue
            seen.add(appid)
            games.append({"appid": appid, "name": name,
                          "lastPlayed": int(st.get("LastPlayed", "0") or 0),
                          "size": int(st.get("SizeOnDisk", "0") or 0)})
    games.sort(key=lambda g: (-g["lastPlayed"], g["name"].lower()))
    return games


CHOICES_LOCK = threading.Lock()


def game_key(g):
    return g["id"] if "id" in g else f"steam:{g['appid']}"


def load_choices():
    try:
        d = json.loads(CHOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}  # none yet, or unreadable: show everything
    return {"hidden": list(d.get("hidden", [])), "pinned": list(d.get("pinned", []))}


def library():
    """(games to show, names of hidden games), with the □ choices applied: pinned first, newest pin first."""
    c = load_choices()
    games = load_games() + steam_games()
    for g in games:
        g["key"] = game_key(g)
        g["pinned"] = g["key"] in c["pinned"]
    shown = [g for g in games if g["key"] not in c["hidden"]]
    shown.sort(key=lambda g: c["pinned"].index(g["key"]) if g["pinned"] else len(c["pinned"]))  # stable: rest keep order
    return shown, [g["name"] for g in games if g["key"] in c["hidden"]]


def set_choice(action, key=""):
    """The launcher's □ menu: hide, pin or unpin one game, or show every hidden game again."""
    with CHOICES_LOCK:
        c = load_choices()
        if action == "unhide-all":
            c["hidden"] = []
        elif action in ("hide", "pin", "unpin"):
            if key not in {game_key(g) for g in load_games() + steam_games()}:
                raise KeyError(key)
            c = {k: [x for x in v if x != key] for k, v in c.items()}
            if action == "hide":
                c["hidden"].append(key)
            elif action == "pin":
                c["pinned"].insert(0, key)
        else:
            raise ValueError(f"unknown action {action!r}")
        tmp = CHOICES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"_help": "Games hidden or pinned with the launcher's Square button. Delete this file to reset.",
                                   **c}, indent=2), encoding="utf-8")
        tmp.replace(CHOICES_FILE)  # all or nothing, even if the PC goes off mid-write


def art_file(appid, kind="poster"):
    folder = steam_path() / "appcache" / "librarycache"
    names = ("library_hero.jpg",) if kind == "hero" else ("library_600x900.jpg", "header.jpg")
    for n in names:
        for p in (folder / str(appid) / n, folder / f"{appid}_{n}"):
            if p.exists():
                return p
    return None


# ---------------------------------------------------------------- Win32 input

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

KEYUP, UNICODE, EXTENDED = 0x2, 0x4, 0x1
KEYS = {  # name: (virtual key, extended)
    "up": (0x26, True), "down": (0x28, True), "left": (0x25, True), "right": (0x27, True),
    "enter": (0x0D, False), "escape": (0x1B, False),
    "backspace": (0x08, False),
    "volup": (0xAF, True), "voldown": (0xAE, True), "mute": (0xAD, True),
    "playpause": (0xB3, True), "next": (0xB0, True), "prev": (0xB1, True),
}


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk, up=False, ext=False):
    i = INPUT(type=1)
    i.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=(KEYUP if up else 0) | (EXTENDED if ext else 0), time=0, dwExtraInfo=0)
    return i


def press(name):
    vk, ext = KEYS[name]
    _send([_key(vk, False, ext), _key(vk, True, ext)])


def alt_f4():
    _send([_key(0x12), _key(0x73), _key(0x73, True), _key(0x12, True)])


def type_text(text):
    inputs = []
    for ch in text[:500]:
        if ch == "\n":
            inputs += [_key(0x0D), _key(0x0D, True)]
            continue
        for unit in [int.from_bytes(ch.encode("utf-16-le")[i:i + 2], "little")
                     for i in range(0, len(ch.encode("utf-16-le")), 2)]:
            for up in (False, True):
                i = INPUT(type=1)
                i.u.ki = KEYBDINPUT(wVk=0, wScan=unit, dwFlags=UNICODE | (KEYUP if up else 0), time=0, dwExtraInfo=0)
                inputs.append(i)
    if inputs:
        _send(inputs)


def mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=0)
    i.u.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=0)
    _send([i])


def mouse_move(dx, dy):
    mouse(0x0001, int(dx), int(dy))


def mouse_click(button):
    down, up = (0x0008, 0x0010) if button == "right" else (0x0002, 0x0004)
    mouse(down)
    mouse(up)


def mouse_scroll(dy):
    mouse(0x0800, data=int(dy))


# ---------------------------------------------------------------- windows

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)


def window_title(h):
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def window_class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def find_launcher():
    found = []

    def cb(h, _):
        if user32.IsWindowVisible(h) and window_title(h).startswith(LAUNCHER_TITLE):
            found.append(h)
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.BringWindowToTop.argtypes = (wintypes.HWND,)


def focus_window(h):
    user32.ShowWindow(h, 9)  # SW_RESTORE
    _send([_key(0x12), _key(0x12, True)])  # an Alt tap lets us take the foreground
    if user32.SetForegroundWindow(h) and user32.GetForegroundWindow() == h:
        return
    # Full-screen apps (Steam Big Picture) hold on harder: briefly share the front window's input
    # queue, which lets Windows hand the focus over.
    fg = user32.GetForegroundWindow()
    me, them = kernel32.GetCurrentThreadId(), user32.GetWindowThreadProcessId(fg, None)
    attached = bool(fg) and them != me and user32.AttachThreadInput(me, them, True)
    user32.BringWindowToTop(h)
    user32.SetForegroundWindow(h)
    if attached:
        user32.AttachThreadInput(me, them, False)
    if user32.GetForegroundWindow() != h:
        user32.SwitchToThisWindow(h, True)  # last resort


def edge_kiosk(url, profile, user_agent=None):
    edge = CONFIG.get("edge")
    if not edge:
        raise RuntimeError("Microsoft Edge not found; set \"edge\" in config.json")
    # --app + --start-fullscreen instead of --kiosk: kiosk is always InPrivate, which forgets sign-ins
    # autoplay flag: launcher sounds come from controller presses, which browsers don't count as a click
    args = [edge, f"--app={url}", "--start-fullscreen", "--no-first-run", "--autoplay-policy=no-user-gesture-required",
            # occlusion/backgrounding off: at boot Edge thinks the window is hidden and shows gray until clicked
            "--disable-features=msImplicitSignin,CalculateNativeWinOcclusion",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            f"--user-data-dir={PROFILES / profile}"]
    if user_agent:
        args.append(f"--user-agent={user_agent}")
    subprocess.Popen(args, creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP


_launcher_spawned = [0.0]
STARTED = time.time()  # when this server process started (sign-in, or a manual restart)


def open_launcher():
    h = find_launcher()
    if h:
        focus_window(h)
    elif time.time() - _launcher_spawned[0] > 15:  # its title isn't set until the page loads
        _launcher_spawned[0] = time.time()
        edge_kiosk(f"http://127.0.0.1:{CONFIG['port']}/launcher", "launcher")

        def bring_forward():  # Windows won't let a window started from the background take focus
            for _ in range(120):  # up to 30 s
                time.sleep(0.25)
                h = find_launcher()
                if h:
                    time.sleep(0.5)
                    focus_window(h)
                    break
            else:
                return
            if time.time() - STARTED > 60:
                return  # not a fresh start: you may be in a game, don't fight for the front
            # At boot other apps (e.g. Steam Big Picture) can open just after and take the front:
            # keep the launcher in front for 20 s, unless something gets launched from it.
            t0 = time.time()
            while time.time() - t0 < 20:
                time.sleep(1)
                if WATCHER.armed_at >= t0:  # something was launched: stop for good, even if the watcher resets
                    break
                h = find_launcher()
                if h and not launcher_in_front():
                    focus_window(h)
        threading.Thread(target=bring_forward, daemon=True).start()


user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
dwmapi = ctypes.WinDLL("dwmapi")


def _cloaked(h):  # hidden system windows (e.g. "Windows Input Experience") report visible but are cloaked
    v = wintypes.DWORD()
    return dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(v), ctypes.sizeof(v)) == 0 and v.value != 0


def visible_windows():
    """Titled, visible top-level app windows (not the launcher, not overlays), front-most first."""
    found = []

    def cb(h, _):
        t = user32.IsWindowVisible(h) and window_title(h)
        # skip tool/no-activate windows: overlays like NVIDIA's must never take focus from a game
        if t and not t.startswith(LAUNCHER_TITLE) and not user32.GetWindowLongW(h, -20) & (0x80 | 0x08000000) \
                and not _cloaked(h):
            found.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
user32.IsWindow.argtypes = (wintypes.HWND,)


def window_exe(h):
    """Lower-case file name of the program that owns window h ("" if it can't be read)."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    ph = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not ph:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(260), wintypes.DWORD(260)
        return Path(buf.value).name.lower() if kernel32.QueryFullProcessImageNameW(ph, 0, buf, ctypes.byref(n)) else ""
    finally:
        kernel32.CloseHandle(ph)


# Store/launcher windows that open on the way to a game; the game is the window that isn't one of these.
LAUNCHER_EXES = {"steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "eadesktop.exe", "ealauncher.exe",
                 "upc.exe", "ubisoftconnect.exe", "launcher.exe", "launcherpatcher.exe", "socialclubhelper.exe"}
RUNNING = {"name": None, "windows": []}  # what was launched last and the windows that opened for it, oldest first


def pick_running(cands):
    """cands: [(hwnd, exe)] still open, oldest first. The newest non-launcher window, else the newest window."""
    games = [h for h, exe in cands if exe not in LAUNCHER_EXES]
    return (games or [h for h, _ in cands] or [None])[-1]


def running_window():
    """The launched game/app's window while it's still open, else None."""
    alive = [(h, window_exe(h)) for h in RUNNING["windows"] if user32.IsWindow(h) and user32.IsWindowVisible(h)]
    return pick_running(alive)


def focus_what_opens(before):
    """Windows won't give focus to a window our background process started (Steam, a game...), so the
    controller wouldn't reach it. Focus each new window as it appears; stop 10 s after the last one.
    The windows are also remembered for Resume / Close game."""
    # shortcut: a game window that appears more than 10 s after the last launcher window isn't tracked;
    # keep watching longer if slow launchers (Rockstar) turn out to need it.
    seen, last, t0 = set(before), 0.0, time.time()
    while time.time() - t0 < 60:
        time.sleep(0.5)
        new = [h for h in visible_windows() if h not in seen]
        seen.update(new)
        if new:
            RUNNING["windows"] += new
            time.sleep(0.3)  # let it finish appearing
            focus_window(new[0])
            last = time.time()
        elif last and time.time() - last > 10:
            return


def close_launcher():
    h = find_launcher()
    if h:
        user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE


# After something is launched, bring the launcher back once you return to the bare desktop.
class ReturnWatcher(threading.Thread):
    DESKTOP = {"Progman", "WorkerW", "Shell_TrayWnd", ""}

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.armed_at = 0.0
        self.saw_app = False

    def arm(self):
        with self.lock:
            self.armed_at, self.saw_app = time.time(), False

    def run(self):
        while True:
            time.sleep(1.5)
            with self.lock:
                if not self.armed_at:
                    continue
                if time.time() - self.armed_at > 6 * 3600:
                    self.armed_at = 0
                    continue
                fg = user32.GetForegroundWindow()
                cls = window_class(fg) if fg else ""
                is_launcher = bool(fg) and window_title(fg).startswith(LAUNCHER_TITLE)
                if fg and not is_launcher and cls not in self.DESKTOP:
                    self.saw_app = True
                elif is_launcher and self.saw_app:  # you came back to it yourself
                    self.armed_at = 0
                elif self.saw_app and cls in self.DESKTOP:
                    self.armed_at = 0
                    h = find_launcher()
                    if h:
                        log.info("back on the desktop; restoring launcher")
                        focus_window(h)


WATCHER = ReturnWatcher()


# ---------------------------------------------------------------- controller
# The server reads the controller itself (through SDL, via pygame), so it works whether or not
# Steam is running. Presses only go to the launcher page while the launcher is in front.

LISTENERS = []  # one queue per open launcher page
LISTENERS_LOCK = threading.Lock()
PAD_STATUS = "pad:none"  # last controller/battery state sent to the launcher; new pages get it on connect


def emit(action):
    # shortcut: only the newest launcher page gets presses, so a second open copy can't launch too;
    # assumes the TV's page is the newest, revisit if you ever run two launchers on purpose.
    with LISTENERS_LOCK:
        if LISTENERS:
            LISTENERS[-1].put(action)


def pad_status_for(levels):
    """pad:none, or the weakest battery among SDL power levels (wired counts as charged)."""
    order = ["empty", "low", "medium", "full", "max", "wired"]
    levels = [lv if lv in order else "max" for lv in levels]  # "unknown": don't alarm anyone
    return "pad:" + (min(levels, key=order.index) if levels else "none")


def launcher_in_front():
    fg = user32.GetForegroundWindow()
    return bool(fg) and window_title(fg).startswith(LAUNCHER_TITLE)


def steam_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq steam.exe", "/nh"], capture_output=True,
                         text=True, creationflags=0x08000000).stdout
    return "steam.exe" in out.lower()


def controller_loop():
    """Keep the controller reader alive: if it ever crashes, log it and start it again."""
    while True:
        try:
            if _controller_loop() is False:
                return  # pygame missing; nothing to retry
        except Exception:  # noqa: BLE001
            log.exception("controller reader crashed; restarting in 3 s")
        time.sleep(3)


def _controller_loop():
    global PAD_STATUS
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"  # read it even when our window isn't focused
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    try:
        import pygame
        from pygame._sdl2 import controller as gc
    except ImportError:
        log.warning("pygame not installed: run  python -m pip install pygame  for controller support")
        return False
    pygame.display.init()  # needed for SDL's event queue; no window is opened
    pygame.joystick.init()
    gc.init()
    pads = {}
    for i in range(pygame.joystick.get_count()):  # already plugged in (matters after a restart)
        if gc.is_controller(i):
            c = gc.Controller(i)
            pads[c.as_joystick().get_instance_id()] = c
    B = pygame
    buttons = {B.CONTROLLER_BUTTON_A: "a", B.CONTROLLER_BUTTON_B: "b", B.CONTROLLER_BUTTON_Y: "y",
               B.CONTROLLER_BUTTON_DPAD_UP: "up", B.CONTROLLER_BUTTON_DPAD_DOWN: "down",
               B.CONTROLLER_BUTTON_DPAD_LEFT: "left", B.CONTROLLER_BUTTON_DPAD_RIGHT: "right",
               B.CONTROLLER_BUTTON_X: "x", B.CONTROLLER_BUTTON_GUIDE: "guide",  # SDL's X is the west button: □
               B.CONTROLLER_BUTTON_LEFTSHOULDER: "l1", B.CONTROLLER_BUTTON_RIGHTSHOULDER: "r1"}
    held = {}  # direction -> time of next repeat
    stick = {"x": 0, "y": 0}
    dpad = set()
    log.info("controller support on")
    next_status = 0.0

    def pad_status():
        levels = []
        for c in pads.values():
            try:
                levels.append(c.as_joystick().get_power_level())
            except pygame.error:
                continue
        return pad_status_for(levels)

    def act(action):
        if action == "guide":  # PS / Xbox button: bring up the launcher (Steam uses it when running)
            if not launcher_in_front() and not steam_running():
                open_launcher()
        elif launcher_in_front():
            emit(action)

    while True:
        for e in pygame.event.get():
            if e.type == B.CONTROLLERDEVICEADDED:
                try:
                    c = gc.Controller(e.device_index)
                    pads[c.as_joystick().get_instance_id()] = c
                    log.info("controller connected: %s", c.name)
                except pygame.error:
                    pass
            elif e.type == B.CONTROLLERDEVICEREMOVED:
                pads.pop(e.instance_id, None)
            elif e.type == B.CONTROLLERBUTTONDOWN and e.button in buttons:
                a = buttons[e.button]
                if a in ("up", "down", "left", "right"):
                    dpad.add(a)
                else:
                    act(a)
            elif e.type == B.CONTROLLERBUTTONUP and e.button in buttons:
                dpad.discard(buttons[e.button])
            elif e.type == B.CONTROLLERAXISMOTION:
                if e.axis == B.CONTROLLER_AXIS_LEFTX:
                    stick["x"] = e.value
                elif e.axis == B.CONTROLLER_AXIS_LEFTY:
                    stick["y"] = e.value
        # directions from d-pad or left stick, repeating while held
        now = time.time()
        if now >= next_status:  # battery changes slowly; check every 5 s, tell the page only on change
            next_status, s = now + 5, pad_status()
            if s != PAD_STATUS:
                PAD_STATUS = s
                emit(s)
        dirs = set(dpad)
        dz = 0.6 * 32767
        if stick["x"] < -dz: dirs.add("left")
        if stick["x"] > dz: dirs.add("right")
        if stick["y"] < -dz: dirs.add("up")
        if stick["y"] > dz: dirs.add("down")
        for d in list(held):
            if d not in dirs:
                del held[d]
        for d in dirs:
            if d not in held:
                held[d] = now + 0.38
                act(d)
            elif now >= held[d]:
                held[d] = now + 0.11
                act(d)
        time.sleep(0.01)


# ---------------------------------------------------------------- launching & power

def launch_app(app_id):
    apps, _ = load_apps()
    app = next((a for a in apps + load_games() if a.get("id") == app_id), None)
    if not app:
        raise KeyError(app_id)
    kind, target = app.get("kind"), os.path.expandvars(app.get("target", ""))
    if kind == "url":
        os.startfile(target)
    elif kind == "exe":
        subprocess.Popen([target] + list(app.get("args", [])), cwd=str(Path(target).parent),
                         creationflags=0x00000008 | 0x00000200)
    elif kind == "web":
        edge_kiosk(target, f"web-{app['id']}", TV_USER_AGENT if app.get("tv") else None)
    else:
        raise ValueError(f"unknown kind {kind!r}")
    log.info("launched app %s", app_id)
    return app["name"]


def launch_game(appid):
    appid = int(appid)
    game = next((g for g in steam_games() if g["appid"] == appid), None)
    if not game:
        raise KeyError(appid)
    os.startfile(f"steam://rungameid/{appid}")
    log.info("launched game %s", appid)
    return game["name"]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]


def _enable_shutdown_privilege():
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):
        return
    luid = LUID()
    advapi32.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(luid))
    tp = TOKEN_PRIVILEGES(1, luid, 0x2)
    advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
    kernel32.CloseHandle(token)


def power(action):
    def later():
        time.sleep(1.0)  # let the HTTP reply go out first
        log.info("power: %s", action)
        if action == "sleep":
            _enable_shutdown_privilege()
            ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
        elif action == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "0"], creationflags=0x08000000)
        elif action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "0"], creationflags=0x08000000)

    if action not in ("sleep", "restart", "shutdown"):
        raise ValueError(action)
    threading.Thread(target=later, daemon=True).start()


# ---------------------------------------------------------------- network helpers

def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    good = []
    for ip in ips:
        a = ipaddress.ip_address(ip)
        if a.is_private and not a.is_loopback and not a.is_link_local:
            good.append(ip)
    good.sort()
    try:  # put the address Windows uses for internet traffic first (no packets are sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            primary = s.getsockname()[0]
        if primary in good:
            good.remove(primary)
            good.insert(0, primary)
    except OSError:
        pass
    return good


def client_kind(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "deny"
    if a.is_loopback:
        return "local"
    if a.is_private and not a.is_link_local:
        return "lan"
    return "deny"  # e.g. VPN ranges like Radmin's 26.x.x.x


def host_ok(host):
    host = (host or "").rsplit(":", 1)[0].strip("[]").lower()
    if host in ("localhost", socket.gethostname().lower()):
        return True
    try:
        a = ipaddress.ip_address(host)
        return a.is_loopback or a.is_private
    except ValueError:
        return False


# ---------------------------------------------------------------- HTTP

STATIC = {"/launcher": "launcher.html", "/remote": "remote.html"}


class Handler(BaseHTTPRequestHandler):
    server_version = "CouchRemote/1.0"

    def log_message(self, fmt, *args):
        pass

    # -- helpers
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if ctype.startswith("image/") else "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def stream_events(self):
        """Controller presses for the launcher page, as a never-ending text stream."""
        import queue
        q = queue.Queue()
        with LISTENERS_LOCK:
            LISTENERS.append(q)
        q.put(PAD_STATUS)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except OSError:
            pass  # page closed
        finally:
            with LISTENERS_LOCK:
                LISTENERS.remove(q)

    def gate(self, api):
        """Return the client kind, or None after sending an error."""
        kind = client_kind(self.client_address[0])
        if kind == "deny" or not host_ok(self.headers.get("Host")):
            self.send_json({"error": "forbidden"}, 403)
            return None
        if not api:
            return kind
        # Custom header forces a CORS preflight, which we never approve, so other websites can't call us.
        if self.headers.get("X-Couch") != "1":
            self.send_json({"error": "missing header"}, 403)
            return None
        return kind  # no PIN, by choice: anyone on the home network may use the remote

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 10000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    # -- GET
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            kind = self.gate(True)
            if not kind:
                return
            if path == "/api/ping":  # cheap "still there?" check for the phone
                return self.send_json({"ok": True, "name": socket.gethostname()})
            if path == "/api/events" and kind == "local":
                return self.stream_events()
            if path == "/api/info":
                apps, _ = load_apps()
                games, hidden = library()
                info = {"name": socket.gethostname(), "apps": apps, "games": games, "hidden": hidden}
                if kind == "local":
                    info["urls"] = [f"http://{ip}:{CONFIG['port']}/remote" for ip in lan_ips()]
                    if running_window():
                        info["running"] = {"name": RUNNING["name"]}
                return self.send_json(info)
            return self.send_json({"error": "not found"}, 404)

        kind = self.gate(False)
        if not kind:
            return
        if path == "/":
            path = "/launcher" if kind == "local" else "/remote"
        if path in STATIC:
            return self.send_file(WEB / STATIC[path], "text/html; charset=utf-8")
        if path in ("/icon.png", "/poster.webp", "/steelball.png"):
            return self.send_file(WEB / path[1:], "image/png" if path.endswith(".png") else "image/webp")
        m = re.fullmatch(r"/art/(\d+)(/hero)?", path)
        if m:
            f = art_file(int(m.group(1)), "hero" if m.group(2) else "poster")
            if f:
                return self.send_file(f, "image/jpeg")
        self.send_json({"error": "not found"}, 404)

    # -- POST
    def do_POST(self):
        kind = self.gate(True)
        if not kind:
            return
        path, b = urlparse(self.path).path, self.body()
        try:
            if path == "/api/launch":
                before = visible_windows()
                name = launch_game(b["game"]) if "game" in b else launch_app(str(b.get("id")))
                RUNNING.update(name=name, windows=[])
                threading.Thread(target=focus_what_opens, args=(before,), daemon=True).start()
                WATCHER.arm()
                return self.send_json({"ok": True, "name": name})
            if path == "/api/key":
                if b.get("key") not in KEYS:
                    return self.send_json({"error": "unknown key"}, 400)
                press(b["key"])
            elif path == "/api/text":
                type_text(str(b.get("text", "")))
            elif path == "/api/mouse":
                mouse_move(max(-500, min(500, float(b.get("dx", 0)))), max(-500, min(500, float(b.get("dy", 0)))))
            elif path == "/api/click":
                mouse_click("right" if b.get("button") == "right" else "left")
            elif path == "/api/scroll":
                mouse_scroll(max(-1200, min(1200, float(b.get("dy", 0)))))
            elif path == "/api/power":
                power(str(b.get("action")))
            elif path == "/api/games":
                set_choice(str(b.get("action")), str(b.get("key", "")))
            elif path == "/api/window":
                act = b.get("action")
                if act == "launcher":
                    open_launcher()
                elif act == "close-launcher":
                    close_launcher()
                elif act in ("resume", "close-game"):
                    h = running_window()
                    if not h:
                        return self.send_json({"error": "It's no longer running"}, 409)
                    if act == "resume":
                        focus_window(h)
                    else:
                        user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE: same as the game's own close button
                elif act == "close-app":
                    fg = user32.GetForegroundWindow()
                    if fg and window_class(fg) not in ReturnWatcher.DESKTOP:
                        alt_f4()
                else:
                    return self.send_json({"error": "unknown action"}, 400)
            else:
                return self.send_json({"error": "not found"}, 404)
            return self.send_json({"ok": True})
        except (KeyError, ValueError) as e:
            return self.send_json({"error": f"bad request: {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            log.exception("request failed")
            return self.send_json({"error": str(e)}, 500)


def already_running(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def main():
    port = CONFIG["port"]
    want_open = "--open" in sys.argv
    if already_running(port):
        if want_open:
            import urllib.request  # only needed here; keeps normal startup lighter
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/window", method="POST",
                                         data=b'{"action":"launcher"}',
                                         headers={"X-Couch": "1", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        print("Already running.")
        return
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    WATCHER.start()
    threading.Thread(target=controller_loop, daemon=True).start()
    log.info("listening on port %s; LAN: %s", port, lan_ips())
    print(f"Couch Remote on http://127.0.0.1:{port}  (phone: {', '.join(lan_ips()) or 'no LAN IP'})")
    if want_open:
        threading.Timer(0.5, open_launcher).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
