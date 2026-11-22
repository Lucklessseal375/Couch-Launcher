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
import shutil
import socket
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))  # audio.py and padspeaker.py sit next to this file
import audio  # noqa: E402
import padspeaker  # noqa: E402

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
    """Non-Steam games from apps.json (e.g. Epic); their last-played time is kept in choices.json."""
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


UPDATING = 256 | 1024 | 1048576 | 2097152 | 4194304  # Steam StateFlags: update running/started, downloading, staging, committing


def update_status(st):
    """What a tile says about a Steam update, from the appmanifest's AppState; None when there isn't one."""
    flags = int(st.get("StateFlags", "0") or 0)
    if flags & 512:
        return "Update paused in Steam"
    if flags & UPDATING:
        done = sum(int(st.get(k, "0") or 0) for k in ("BytesDownloaded", "BytesStaged"))
        total = sum(int(st.get(k, "0") or 0) for k in ("BytesToDownload", "BytesToStage"))
        return f"Updating {done * 100 // total}%" if total else "Updating"
    return "Update waiting in Steam" if flags & 2 else None


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
        try:
            free = shutil.disk_usage(lib).free  # room left on that library's drive, for the details dialog
        except OSError:
            free = 0
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                st = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
                appid = int(st.get("appid", 0))
            except (OSError, ValueError):
                continue
            name = st.get("name", "")
            if not appid or appid in seen or appid in hidden or TOOL_NAME.search(name):
                continue
            update = update_status(st)
            # Steam drops "fully installed" (4) while an update runs; installed depots say it was installed before
            if not (int(st.get("StateFlags", "0") or 0) & 4 or update and st.get("InstalledDepots")):
                continue
            seen.add(appid)
            games.append({"appid": appid, "name": name,
                          "lastPlayed": int(st.get("LastPlayed", "0") or 0),
                          "size": int(st.get("SizeOnDisk", "0") or 0), "free": free,
                          **({"update": update} if update else {})})
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
    return {"hidden": list(d.get("hidden", [])), "pinned": list(d.get("pinned", [])), "audio": d.get("audio"),
            "played": dict(d.get("played", {}))}


def save_choices(c):
    tmp = CHOICES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"_help": "Set from the launcher: games hidden or pinned with the Square button, and "
                                        "the audio output Windows keeps as default. Delete this file to reset.",
                               **c}, indent=2), encoding="utf-8")
    tmp.replace(CHOICES_FILE)  # all or nothing, even if the PC goes off mid-write


def steam_playtime():
    """{appid: minutes played} for the Steam account used last on this PC ({} if Steam hasn't saved any)."""
    files = sorted((steam_path() / "userdata").glob("*/config/localconfig.vdf"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        node = parse_vdf(files[0].read_text(encoding="utf-8", errors="replace")) if files else {}
    except OSError:
        return {}
    for key in ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"):  # Steam's key case varies
        node = next((v for k, v in node.items() if k.lower() == key.lower() and isinstance(v, dict)), {})
    return {int(k): int(v["Playtime"]) for k, v in node.items()
            if k.isdigit() and isinstance(v, dict) and str(v.get("Playtime", "")).isdigit()}


def library():
    """(games to show, names of hidden games), with the □ choices applied: pinned first, newest pin first."""
    c = load_choices()
    games = load_games() + steam_games()
    played = steam_playtime()
    for g in games:
        g["key"] = game_key(g)
        g["pinned"] = g["key"] in c["pinned"]
        if "appid" in g:
            g["playtime"] = played.get(g["appid"], 0)
        else:  # Steam keeps its own LastPlayed; other stores' games get the time we launched them
            g["lastPlayed"] = int(c["played"].get(g["key"], 0))
    games.sort(key=lambda g: -g["lastPlayed"])  # most recently played first, across stores (stable: names stay sorted)
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
            for k in ("hidden", "pinned"):
                c[k] = [x for x in c[k] if x != key]
            if action == "hide":
                c["hidden"].append(key)
            elif action == "pin":
                c["pinned"].insert(0, key)
        else:
            raise ValueError(f"unknown action {action!r}")
        save_choices(c)


# ---------------------------------------------------------------- audio output

# Mixers, virtual cables and Steam's streaming device: real outputs only in the picker.
VIRTUAL_AUDIO = re.compile(r"voicemeeter|vb-audio|sonar|steam streaming|virtual", re.I)


def audio_state():
    """{"devices": [{id, name, default}], "current": {id, name} or None}; devices are real outputs only."""
    found = audio.outputs()
    cur = next((d for d in found if d["default"]), None)
    return {"devices": [d for d in found if not VIRTUAL_AUDIO.search(d["name"])],
            "current": cur and {"id": cur["id"], "name": cur["name"]}}


def set_audio(device_id):
    """Make it Windows' default output for everything, and remember it so keep_audio holds it there."""
    dev = next((d for d in audio.outputs() if d["id"] == device_id), None)
    if not dev:
        raise KeyError(device_id)
    audio.set_default(device_id)
    with CHOICES_LOCK:
        c = load_choices()
        c["audio"] = {"id": dev["id"], "name": dev["name"]}
        save_choices(c)
    log.info("audio output: %s", dev["name"])
    return dev["name"]


def audio_replaced(want, ids, names):
    """The outputs to switch away from so `want` is the default again (names), or None to leave it as is:
    the chosen output is off (TV asleep), or Steam Remote Play is using its own device."""
    was = {names.get(i, "nothing") for i in ids if i != want["id"]}
    if not was or want["id"] not in names or any("steam streaming" in n.lower() for n in was):
        return None
    return was


def keep_audio():
    """Windows moves the default output when devices come and go (the TV waking up, a headset turning on).
    Put the chosen one back as soon as it's there again. Leaves Steam Remote Play's device alone, and backs off
    for 10 minutes if something keeps taking the default (a mixer app like Sonar), so the two don't fight."""
    restored = []
    while True:
        time.sleep(3)
        try:
            want = load_choices()["audio"]
            ids = audio.default_ids() if want else ()
            if all(i == want["id"] for i in ids):
                continue
            was = audio_replaced(want, ids, {d["id"]: d["name"] for d in audio.outputs()})
            if not was:
                continue
            now = time.time()
            restored = [t for t in restored if now - t < 60]
            if len(restored) >= 3:
                log.warning("something keeps changing the audio output; leaving it for 10 minutes")
                time.sleep(600)
                restored = []
                continue
            audio.set_default(want["id"])
            restored.append(now)
            log.info("audio output back to %s (was %s)", want["name"], ", ".join(sorted(was)))
        except Exception:  # noqa: BLE001
            log.exception("audio keeper")
            time.sleep(30)


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


# The controller as a TV remote, only while a TV site (YouTube's TV app) is in front: ✕ select, ○ back,
# □ play/pause, L1/R1 previous/next.
TV_KEYS = {"up": "up", "down": "down", "left": "left", "right": "right", "a": "enter", "b": "escape",
           "x": "playpause", "l1": "prev", "r1": "next"}


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


def edge_kiosk(url, profile, user_agent=None, extra=()):
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
    args += list(extra)
    subprocess.Popen(args, creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP


# ---------------------------------------------------------------- TV sites (YouTube's TV app)
# The --user-agent flag alone no longer gets YouTube's TV app: Edge still tells the site it is desktop Edge on Windows
# (Sec-CH-UA client hints, which an extension can't strip either), so youtube.com/tv redirects to the desktop site. A
# DevTools session on the window sets the whole identity to a Samsung TV; it only holds while it stays attached.
TV_HINTS = {"brands": [], "fullVersion": "", "platform": "Tizen", "platformVersion": "6.0", "architecture": "arm",
            "model": "SMART-TV", "mobile": False}
TV_PIDS = set()  # Edge browser processes showing a TV site: the controller drives them with TV-remote keys
TV_OPEN = {}  # profile -> its Edge browser pid while its TV window is open
# YouTube's TV app has no way out: back from home goes to its account screen, and back there does nothing (on a TV the
# system closes the app). So ○ there, or a ○ that changes nothing on screen, asks us to close the window.
TV_EXIT_JS = """(() => {
  const exit = window.couchExit ? () => window.couchExit("") : () => {};  // a DevTools binding (YouTube mutes the console)
  addEventListener("keydown", e => {
    if (e.key !== "Escape" || !e.isTrusted) return;
    if (document.querySelector("ytlr-welcome")) return exit();
    const before = document.body ? document.body.innerText : "";
    setTimeout(() => { if (document.body && document.body.innerText === before) exit(); }, 700);
  }, true);
})();"""


class Cdp:
    """Just enough websocket client for one DevTools target (text frames, masked sends, no Origin header, so only
    local programs can connect; web pages can't)."""

    def __init__(self, ws_url):
        import base64
        host, rest = ws_url[len("ws://"):].split("/", 1)
        h, port = host.split(":")
        self.s = socket.create_connection((h, int(port)), timeout=15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.s.recv(1)
            if not chunk:
                raise ConnectionError("devtools closed the handshake")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise ConnectionError(resp[:80])
        self.n = 0

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("devtools closed")
            buf += chunk
        return buf

    def recv(self):
        out = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = int.from_bytes(self._read(2), "big")
            elif n == 127:
                n = int.from_bytes(self._read(8), "big")
            out += self._read(n)
            if b1 & 0x0F == 0x8:
                raise ConnectionError("devtools closed")
            if b1 & 0x80:
                return json.loads(out.decode() or "{}")

    def send(self, method, **params):
        self.n += 1
        data = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        n = len(data)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + n.to_bytes(2, "big"))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            msg = self.recv()
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})


def edge_tv(url, profile):
    """Opens a TV site in Edge as a Samsung TV and keeps the DevTools session open until the window closes."""
    import urllib.request
    h = TV_OPEN.get(profile) and pid_window(TV_OPEN[profile])
    if h:  # already open: a second Edge launch on the profile would only add a blank window
        focus_window(h)
        return
    port_file = PROFILES / profile / "DevToolsActivePort"
    end_profile_edge(profile)  # nothing of ours is open on it (checked above): a leftover would take the launch
    port_file.unlink(missing_ok=True)
    # a black page until YouTube loads (about:blank is white); port 0: Edge picks a free one
    edge_kiosk("data:text/html,<title>YouTube</title><body bgcolor=black>", profile, TV_USER_AGENT,
               extra=["--remote-debugging-port=0"])
    for _ in range(100):
        try:
            port = int(port_file.read_text().split()[0])
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2))
            page = next(p for p in pages if p.get("type") == "page")
            break
        except (OSError, ValueError, IndexError, StopIteration):
            time.sleep(0.15)
    else:
        log.warning("TV mode: Edge's DevTools port never came up; %s may open as the desktop site", url)
        return
    pid = None
    try:
        browser = Cdp(json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2))["webSocketDebuggerUrl"])
        pid = next((p["id"] for p in browser.send("SystemInfo.getProcessInfo").get("processInfo", []) if p.get("type") == "browser"), None)
        browser.s.close()
    except (OSError, ValueError, RuntimeError, KeyError):
        pass
    try:
        cdp = Cdp(page["webSocketDebuggerUrl"])
        cdp.send("Emulation.setUserAgentOverride", userAgent=TV_USER_AGENT, userAgentMetadata=TV_HINTS)
        cdp.send("Page.enable")  # for the script below
        cdp.send("Page.addScriptToEvaluateOnNewDocument", source=TV_EXIT_JS)
        cdp.send("Runtime.enable")
        cdp.send("Runtime.addBinding", name="couchExit")  # the script calls it; it arrives here as an event
        cdp.send("Page.navigate", url=url)
        if pid:
            TV_PIDS.add(pid)
            TV_OPEN[profile] = pid
        log.info("TV mode: %s open as a TV (edge pid %s)", url, pid)
        cdp.s.settimeout(None)
        while True:  # stay attached: the TV identity lasts only as long as this session
            m = cdp.recv()
            if m.get("method") == "Runtime.bindingCalled" and m.get("params", {}).get("name") == "couchExit":
                h = pid and pid_window(pid)
                if h:
                    log.info("TV mode: back on YouTube's last screen; closing it")
                    user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
    except (OSError, ValueError, RuntimeError, ConnectionError) as e:
        log.info("TV mode: %s closed (%s)", url, e)
    finally:
        TV_PIDS.discard(pid)
        TV_OPEN.pop(profile, None)
        if not (pid and pid_window(pid)):  # its window is gone: back to the launcher, and no Edge left behind it
            open_launcher()  # focuses it, or opens it again; Windows would put whatever was behind in front
            end_profile_edge(profile)


def window_pid(h):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def end_profile_edge(profile):
    """Ends any Edge still running on this profile. Edge can linger with no window after its window closes, and a
    later launch on the profile is handed to it, which shows a blank new-tab page instead of the site."""
    stale = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like "
                            f"'*{PROFILES / profile}*' }} | ForEach-Object {{ $_.ProcessId }}"],
                           capture_output=True, text=True, creationflags=0x08000000).stdout.split()
    for pid in stale:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True, creationflags=0x08000000)
    if stale:
        log.info("TV mode: ended Edge left running on %s (%s)", profile, ", ".join(stale))
        time.sleep(1)


def pid_window(pid):
    """A visible, titled top-level window of process pid, or None."""
    found = []

    def cb(h, _):
        if user32.IsWindowVisible(h) and window_pid(h) == pid and window_title(h):
            found.append(h)
            return False
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def allow_audio_names(profile, origin):
    """Grants our own page the media permission in its Edge profile, so it can see audio device names (to play
    sounds on the DualSense speaker) with no prompt and no unsupported command-line flag (which shows a warning
    banner). Edge must not be running on the profile; before its first run there is no file yet and Edge asks once."""
    prefs = PROFILES / profile / "Default" / "Preferences"
    try:
        data = json.loads(prefs.read_text(encoding="utf-8"))
        ex = data.setdefault("profile", {}).setdefault("content_settings", {}).setdefault("exceptions", {})
        ex.setdefault("media_stream_mic", {})[f"{origin},*"] = {"setting": 1}
        prefs.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass


_launcher_spawned = [0.0]
STARTED = time.time()  # when this server process started (sign-in, or a manual restart)


LAUNCHER_WANTED = [False]  # opened and not sent to the desktop on purpose: keep it alive


def open_launcher():
    LAUNCHER_WANTED[0] = True
    h = find_launcher()
    if h:
        focus_window(h)
    elif time.time() - _launcher_spawned[0] > 15:  # its title isn't set until the page loads
        _launcher_spawned[0] = time.time()
        allow_audio_names("launcher", f"http://127.0.0.1:{CONFIG['port']}")
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
RUNNING = {"name": None, "windows": [], "game_seen": False}  # what was launched last and the windows that opened for it, oldest first


def pick_running(cands, game_seen=False):
    """cands: [(hwnd, exe)] still open, oldest first. The newest non-launcher window, else the newest window, unless the
    game's own window was already seen: then it has closed, and only its store launcher (Epic, Rockstar) is left."""
    games = [h for h, exe in cands if exe not in LAUNCHER_EXES]
    if games or game_seen:
        return (games or [None])[-1]
    return ([h for h, _ in cands] or [None])[-1]


# ---------------------------------------------------------------- task manager (launcher PC row / Menu)
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] +                [(n, ctypes.c_ulonglong) for n in ("total", "avail", "pageTotal", "pageAvail", "virtTotal", "virtAvail", "ext")]


class _PROCENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("prio", ctypes.c_long), ("flags", wintypes.DWORD), ("exe", ctypes.c_wchar * 260)]


class _MEMCOUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] +                [(n, ctypes.c_size_t) for n in ("peakWs", "ws", "a", "b", "c", "d", "page", "peakPage")]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCENTRY))
kernel32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MEMCOUNTERS), wintypes.DWORD)
user32.IsHungAppWindow.argtypes = (wintypes.HWND,)
_cpu_last = [None]


def cpu_percent():
    """Whole-PC processor use since the last call (the task manager polls every 2 s); None on the first call."""
    idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
    kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    val = lambda f: f.hi << 32 | f.lo
    now = (val(idle), val(kern) + val(user))  # kernel time includes idle time
    prev, _cpu_last[0] = _cpu_last[0], now
    if not prev or now[1] <= prev[1]:
        return None
    return max(0, min(100, round(100 * (1 - (now[0] - prev[0]) / (now[1] - prev[1])))))


def process_children():
    """pid -> child pids, from one snapshot of every process."""
    kids, snap = {}, kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    e = _PROCENTRY(dwSize=ctypes.sizeof(_PROCENTRY))
    ok = kernel32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        if e.pid != e.parent:
            kids.setdefault(e.parent, []).append(e.pid)
        ok = kernel32.Process32NextW(snap, ctypes.byref(e))
    kernel32.CloseHandle(snap)
    return kids


def tree_memory(pid, kids):
    """Bytes in use by a program and the processes it started (a browser's tabs, a game's helpers)."""
    total, todo, seen = 0, [pid], set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo += kids.get(p, [])
        ph = kernel32.OpenProcess(0x1000 | 0x0010, False, p)  # query limited info, read memory counters
        if ph:
            m = _MEMCOUNTERS(cb=ctypes.sizeof(_MEMCOUNTERS))
            if kernel32.K32GetProcessMemoryInfo(ph, ctypes.byref(m), m.cb):
                total += m.ws
            kernel32.CloseHandle(ph)
    return total


def task_list():
    mem = _MEMSTATUS(dwLength=ctypes.sizeof(_MEMSTATUS))
    kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    kids, apps, seen = process_children(), [], set()
    for h in visible_windows():
        pid = window_pid(h)
        if window_class(h) in ReturnWatcher.DESKTOP or pid in seen or pid == os.getpid():
            continue
        seen.add(pid)  # one row per program, its front-most window
        name = re.sub(r"\s+-\s+(Profile \d+\s+-\s+)?Microsoft\W*Edge$", "", window_title(h)).strip()
        apps.append({"id": h, "name": name or window_exe(h), "exe": window_exe(h),
                     "bytes": tree_memory(pid, kids), "hung": bool(user32.IsHungAppWindow(h))})
    return {"cpu": cpu_percent(), "memUsed": mem.total - mem.avail, "memTotal": mem.total, "apps": apps}


def task_action(h, action):
    """Switch to, close (as its own close button does) or force-close one of task_list()'s windows."""
    if h not in visible_windows():  # only windows the task manager lists, never an arbitrary handle
        raise ValueError("That app isn't open any more")
    title, exe = window_title(h), window_exe(h)
    log.info("task manager: %s %s (%s)", action, title, exe)
    steam = exe in ("steamwebhelper.exe", "steam.exe")  # Steam's windows belong to a helper Steam restarts at once
    if action == "switch":
        focus_window(h)
    elif action == "close" and steam and "Big Picture" in title:
        open_url("steam://close/bigpicture")  # it ignores close messages; leaving it opens Steam's desktop window
        threading.Thread(target=_tuck_steam_away, args=(set(visible_windows()),), daemon=True).start()
    elif action == "close":
        close_window(h)
    elif action == "force":
        cmd = ["taskkill", "/IM", "steam.exe", "/T", "/F"] if steam else ["taskkill", "/PID", str(window_pid(h)), "/T", "/F"]
        subprocess.run(cmd, capture_output=True, creationflags=0x08000000)
    else:
        raise ValueError(f"unknown action {action!r}")


def close_window(h):
    """What the window's own X button does (WM_SYSCOMMAND SC_CLOSE): apps can still ask to save, and Steam, which
    ignores a bare WM_CLOSE, goes to the tray."""
    user32.PostMessageW(h, 0x0112, 0xF060, 0)


def _tuck_steam_away(before):
    for _ in range(16):  # up to 8 s for Steam's desktop window to appear after Big Picture closes
        time.sleep(0.5)
        new = [h for h in visible_windows() if h not in before and window_exe(h) == "steamwebhelper.exe"]
        if new:
            time.sleep(0.5)
            for h in new:
                close_window(h)
            return


def running_window():
    """The launched game/app's window while it's still open, else None."""
    alive = [(h, window_exe(h)) for h in RUNNING["windows"] if user32.IsWindow(h) and user32.IsWindowVisible(h)]
    return pick_running(alive, RUNNING.get("game_seen", False))


def focus_what_opens(before):
    """Windows won't give focus to a window our background process started (Steam, a game...), so the
    controller wouldn't reach it. Focus each new window as it appears. The windows are also remembered for
    Resume / Close game, so keep watching until the game's own window shows up: store launchers (Epic, then
    Rockstar's) come first, and the game can take minutes. Stop 10 s after a game window, or after 3 minutes."""
    seen, last, t0, name = set(before), 0.0, time.time(), RUNNING["name"]
    while time.time() - t0 < 180 and RUNNING["name"] == name:  # a newer launch takes over
        time.sleep(0.5)
        new = [h for h in visible_windows() if h not in seen]
        seen.update(new)
        if new:
            RUNNING["windows"] += new
            time.sleep(0.3)  # let it finish appearing
            focus_window(new[0])
            if any(window_exe(h) not in LAUNCHER_EXES for h in new):
                last = time.time()
                RUNNING["game_seen"] = RUNNING.get("is_game", False)  # an app tile (Big Picture) stays "running" itself
        elif last and time.time() - last > 10:
            return


def close_launcher():
    LAUNCHER_WANTED[0] = False
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
        gone = 0  # checks in a row with the launcher's window missing on a bare desktop
        while True:
            time.sleep(1.5)
            fg = user32.GetForegroundWindow()
            if LAUNCHER_WANTED[0] and (window_class(fg) if fg else "") in self.DESKTOP and not find_launcher():
                gone += 1
                if gone % 20 == 4:  # ~6 s (then every 30 s): its Edge closed or crashed (seen overnight)
                    log.info("launcher window gone; opening it again")
                    open_launcher()
            else:
                gone = 0
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
                    log.info("back on the desktop; restoring launcher")
                    open_launcher()  # focuses it, or opens it again if its window is gone (closed or crashed)


WATCHER = ReturnWatcher()


# ---------------------------------------------------------------- app icons (store tiles show the real app icon)

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD), ("masks", wintypes.DWORD * 3)]


shell32 = ctypes.WinDLL("shell32")
gdi32 = ctypes.WinDLL("gdi32")
shell32.SHDefExtractIconW.argtypes = (wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.HICON),
                                      ctypes.POINTER(wintypes.HICON), wintypes.UINT)
shell32.SHDefExtractIconW.restype = ctypes.c_long
user32.GetIconInfo.argtypes = (wintypes.HICON, ctypes.POINTER(ICONINFO))
user32.DestroyIcon.argtypes = (wintypes.HICON,)
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = (wintypes.HWND,)
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
gdi32.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT)
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
ICON_CACHE = ROOT / "cache" / "icons"
ICON_LOCK = threading.Lock()


def exe_icon_png(exe, out, size=256):
    """Save the program's own icon, size x size with transparency, as a PNG. False if it has none."""
    hicon = wintypes.HICON()
    if shell32.SHDefExtractIconW(str(exe), 0, 0, ctypes.byref(hicon), None, size) != 0 or not hicon:
        return False
    ii = ICONINFO()
    try:
        if not user32.GetIconInfo(hicon, ctypes.byref(ii)) or not ii.hbmColor:
            return False
        bmi = BITMAPINFOHEADER(biSize=40, biWidth=size, biHeight=-size, biPlanes=1, biBitCount=32)  # top-down BGRA
        buf = ctypes.create_string_buffer(size * size * 4)
        dc = user32.GetDC(None)
        try:
            lines = gdi32.GetDIBits(dc, ii.hbmColor, 0, size, buf, ctypes.byref(bmi), 0)
        finally:
            user32.ReleaseDC(None, dc)
        if lines != size:
            return False
        px = bytearray(buf.raw)
        if not any(px[3::4]):  # an old icon without transparency: make it opaque
            px[3::4] = b"\xff" * (size * size)
        import pygame  # already a dependency (controller); here it just writes the PNG
        pygame.image.save(pygame.image.frombuffer(bytes(px), (size, size), "BGRA"), str(out))
        return True
    finally:
        for bm in (ii.hbmColor, ii.hbmMask):
            if bm:
                gdi32.DeleteObject(bm)
        user32.DestroyIcon(hicon)


def app_icon(app_id):
    """PNG of an app tile's icon (cached; redone when the app updates), or None."""
    apps, _ = load_apps()
    app = next((a for a in apps if a.get("id") == app_id), None)
    if not app:
        return None
    target = os.path.expandvars(app.get("target", ""))
    exe = Path(target) if app.get("kind") == "exe" else steam_path() / "steam.exe" if target.startswith("steam:") else None
    if not exe or not exe.exists():
        return None
    out = ICON_CACHE / f"{app_id}.png"
    with ICON_LOCK:
        if not out.exists() or out.stat().st_mtime < exe.stat().st_mtime:
            ICON_CACHE.mkdir(parents=True, exist_ok=True)
            if not exe_icon_png(exe, out):
                return None
    return out


# ---------------------------------------------------------------- controller
# The server reads the controller itself (through SDL, via pygame), so it works whether or not
# Steam is running. Presses only go to the launcher page while the launcher is in front.

LISTENERS = []  # one queue per open launcher page
LISTENERS_LOCK = threading.Lock()
PAD_STATUS = "pad:none"  # last controller/battery state sent to the launcher; new pages get it on connect
# True once the server reads the controller, False if it can't (then the page uses the Gamepad API).
# None while it's still starting: the page must not fall back then, or both read the pad (seen at logon).
PAD_READER = None
RUMBLES = []  # (when, low, high, ms): haptic pulses waiting for the controller loop
RUMBLE_LOCK = threading.Lock()
LIGHT = [None]  # (r, g, b) the launcher wants on the controllers' light bar; the controller loop applies it
PAD_SPEAKER = padspeaker.Speaker()  # launcher sounds on a wireless DualSense's speaker (the page posts them)
# Haptic cues, felt in the hands while the sounds play on the controller or the TV.
PATTERNS = {"launch": [(0, .45, .25, 110), (.22, .9, .55, 240)],          # the race starts
            "low": [(0, .7, .7, 90), (.2, .7, .7, 90), (.4, .7, .7, 90)],  # battery low
            "shot": [(0, .35, .6, 70)]}  # a screenshot was taken: one short click


def screenshots_dir():
    """Where Windows saves Win+PrtScn screenshots (the Screenshots folder in Pictures, wherever that lives)."""
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]
    u = uuid.UUID("b7bede81-df94-4682-a7d8-57a52620b86f")  # FOLDERID_Screenshots
    g, out = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:])), ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0 and out.value:
        return Path(out.value)
    return Path.home() / "Pictures" / "Screenshots"


def take_screenshot():
    """The Create button, like a PS5's: Windows' own Win+PrtScn, which works over games and saves a PNG."""
    _send([_key(0x5B, False, True), _key(0x2C, False, True), _key(0x2C, True, True), _key(0x5B, True, True)])
    rumble("shot")
    emit("shot")  # the launcher, if it's up, says where it went
    log.info("screenshot (Create button)")


SHOT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def toggle_mic():
    try:
        muted = audio.volume_state()["micMuted"]
        if muted is None:
            return emit("mic:none")
        audio.set_mic_muted(not muted)
    except OSError:
        log.exception("couldn't switch the microphone")
        return
    rumble("shot")
    emit("mic:" + ("on" if muted else "off"))
    log.info("microphone %s (mute button)", "on" if muted else "muted")


def fixed_drives():
    """Each local hard drive: [{"name": "C:", "total", "free"}]."""
    out, mask = [], kernel32.GetLogicalDrives()
    for i in range(26):
        root = f"{chr(65 + i)}:\\"
        if mask >> i & 1 and kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
            try:
                u = shutil.disk_usage(root)
                out.append({"name": root[:2], "total": u.total, "free": u.free})
            except OSError:
                pass
    return out


def media_list():
    """Newest screenshots first, for the launcher's media gallery."""
    d = screenshots_dir()
    try:
        files = [f for f in d.iterdir() if f.suffix.lower() in SHOT_TYPES and f.is_file()]
    except OSError:
        return []
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "time": int(f.stat().st_mtime)} for f in files[:200]]


def rumble(pattern):
    now = time.time()
    with RUMBLE_LOCK:
        RUMBLES.extend((now + t, lo, hi, ms) for t, lo, hi, ms in PATTERNS[pattern])


AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg",
               ".wav": "audio/wav", ".flac": "audio/flac"}


def sound_clips():
    """File names in web/audio/sbr (the launcher's clip slots, see the README there)."""
    folder = WEB / "audio" / "sbr"
    return sorted(p.name for p in folder.iterdir() if p.suffix.lower() in AUDIO_TYPES) if folder.is_dir() else []


def intro_file():
    """The music for startup and game starts: the first audio file you put in web/audio, or None."""
    folder = WEB / "audio"
    return next((p for p in sorted(folder.iterdir()) if p.suffix.lower() in AUDIO_TYPES), None) if folder.is_dir() else None


def emit(action):
    # shortcut: only the newest launcher page gets presses, so a second open copy can't launch too;
    # assumes the TV's page is the newest, revisit if you ever run two launchers on purpose.
    with LISTENERS_LOCK:
        if LISTENERS:
            LISTENERS[-1].put(action)


def pad_status_for(levels):
    """pad:none, or each controller's battery from SDL power levels, comma-separated (the launcher shows one each)."""
    order = ["empty", "low", "medium", "full", "max", "wired"]
    levels = [lv if lv in order else "max" for lv in levels]  # "unknown": don't alarm anyone
    return "pad:" + (",".join(levels) if levels else "none")


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
    global PAD_STATUS, PAD_READER
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"  # read it even when our window isn't focused
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    try:
        import pygame
        from pygame._sdl2 import controller as gc
    except ImportError:
        log.warning("pygame not installed: run  python -m pip install pygame  for controller support")
        PAD_READER = False
        return False
    pygame.display.init()  # needed for SDL's event queue; no window is opened
    pygame.joystick.init()
    gc.init()
    # pygame has no light-bar call; SDL's own works on the controllers pygame opened (USB and Bluetooth alike)
    sdl = ctypes.CDLL(os.path.join(os.path.dirname(pygame.__file__), "SDL2.dll"))
    sdl.SDL_GameControllerFromInstanceID.argtypes, sdl.SDL_GameControllerFromInstanceID.restype = (ctypes.c_int,), ctypes.c_void_p
    sdl.SDL_GameControllerSetLED.argtypes = (ctypes.c_void_p, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8)
    lit = None  # the colour last put on the light bars
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
               B.CONTROLLER_BUTTON_LEFTSHOULDER: "l1", B.CONTROLLER_BUTTON_RIGHTSHOULDER: "r1",
               B.CONTROLLER_BUTTON_START: "options", B.CONTROLLER_BUTTON_BACK: "create",  # DualSense Options, Create
               15: "mic"}  # DualSense mute button (SDL's MISC1)
    held = {}  # direction -> time of next repeat
    stick = {"x": 0, "y": 0}
    dpad = set()
    log.info("controller support on")
    PAD_READER = True
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
        if action == "create":  # anywhere, in games too
            take_screenshot()
        elif action == "mic":  # anywhere: the PC's microphone, like a PS5's mute button
            toggle_mic()
        elif action == "guide":  # PS button: home, or from home back to the game, like a PS5
            h = launcher_in_front() and running_window()
            if h:
                focus_window(h)
            elif not launcher_in_front():
                open_launcher()  # Steam's own PS-button action should be off (Steam: Settings > Controller)
        elif launcher_in_front():
            emit(action)
        elif TV_PIDS and window_pid(user32.GetForegroundWindow()) in TV_PIDS and action in TV_KEYS:
            press(TV_KEYS[action])  # a TV site reads remote keys, not the controller

    while True:
        for e in pygame.event.get():
            if e.type == B.CONTROLLERDEVICEADDED:
                try:
                    c = gc.Controller(e.device_index)
                    pads[c.as_joystick().get_instance_id()] = c
                    lit = None  # give it the current colour too
                    log.info("controller connected: %s", c.name)
                except pygame.error:
                    pass
            elif e.type == B.CONTROLLERDEVICEREMOVED:
                pads.pop(e.instance_id, None)
                dpad.clear()  # a direction held as it dropped would repeat forever
                stick.update(x=0, y=0)
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
                if any(lv in ("low", "empty") for lv in s[4:].split(",")):
                    rumble("low")
                PAD_STATUS = s
                emit(s)
        if LIGHT[0] and LIGHT[0] != lit:  # the light bar colour the launcher asked for, on every controller
            lit = LIGHT[0]
            for iid in pads:
                ptr = sdl.SDL_GameControllerFromInstanceID(iid)
                if ptr:
                    sdl.SDL_GameControllerSetLED(ptr, *lit)
        if RUMBLES:  # haptic pulses that are due, on every connected controller
            with RUMBLE_LOCK:
                due = [r for r in RUMBLES if r[0] <= now]
                RUMBLES[:] = [r for r in RUMBLES if r[0] > now]
            for _, lo, hi, ms in due:
                for c in pads.values():
                    try:
                        c.rumble(lo, hi, ms)
                    except (pygame.error, AttributeError):
                        pass
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

def open_url(url):
    """Opens a store link (com.epicgames.launcher://..., steam://...) by running the program Windows has registered for
    it. os.startfile alone (ShellExecute from a server thread) once did nothing at all for Epic links, three times."""
    scheme = url.split(":", 1)[0]
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{scheme}\shell\open\command") as k:
            cmd = winreg.QueryValueEx(k, "")[0]
    except OSError:
        return os.startfile(url)
    m = re.match(r'\s*"([^"]+)"\s*(.*)$', cmd) or re.match(r"\s*(\S+)\s*(.*)$", cmd)
    exe, rest = m.group(1), m.group(2)
    args = [a.replace("%1", url) for a in (re.findall(r'"[^"]*"|\S+', rest) or ["%1"])]
    args = [a.strip('"') for a in args]
    if "%1" not in rest:
        args.append(url)
    subprocess.Popen([exe] + args, cwd=str(Path(exe).parent), creationflags=0x00000008 | 0x00000200)
    log.info("opened %s link with %s", scheme, Path(exe).name)


def launch_app(app_id):
    apps, _ = load_apps()
    app = next((a for a in apps + load_games() if a.get("id") == app_id), None)
    if not app:
        raise KeyError(app_id)
    kind, target = app.get("kind"), os.path.expandvars(app.get("target", ""))
    if kind == "url":
        open_url(target)
    elif kind == "exe":
        subprocess.Popen([target] + list(app.get("args", [])), cwd=str(Path(target).parent),
                         creationflags=0x00000008 | 0x00000200)
    elif kind == "web":
        if app.get("tv"):
            threading.Thread(target=edge_tv, args=(target, f"web-{app['id']}"), daemon=True).start()
        else:
            edge_kiosk(target, f"web-{app['id']}")
    else:
        raise ValueError(f"unknown kind {kind!r}")
    log.info("launched app %s", app_id)
    if app in load_games():
        with CHOICES_LOCK:
            c = load_choices()
            c["played"][game_key(app)] = int(time.time())
            save_choices(c)
    return app["name"]


def launch_game(appid):
    appid = int(appid)
    game = next((g for g in steam_games() if g["appid"] == appid), None)
    if not game:
        raise KeyError(appid)
    open_url(f"steam://rungameid/{appid}")
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
            if path == "/api/audio":
                return self.send_json(audio_state())
            if path == "/api/padspeaker" and kind == "local":  # can the launcher play on a wireless controller?
                return self.send_json({"ok": PAD_SPEAKER.available()})
            if path == "/api/tasks":
                return self.send_json(task_list())
            if path == "/api/volume":
                return self.send_json(audio.volume_state())
            if path == "/api/storage":
                return self.send_json({"drives": fixed_drives()})
            if path == "/api/media":
                return self.send_json({"shots": media_list()})
            if path == "/api/running":  # cheap: the launcher polls it to keep Now playing current
                return self.send_json({"running": {"name": RUNNING["name"]} if running_window() else None})
            if path == "/api/info":
                apps, _ = load_apps()
                games, hidden = library()
                info = {"name": socket.gethostname(), "apps": apps, "games": games, "hidden": hidden,
                        "padReader": PAD_READER, "intro": bool(intro_file()), "sounds": sound_clips()}
                try:
                    info["audio"] = audio_state()["current"]
                except Exception:  # noqa: BLE001  (optional extra: never lose the library over it)
                    log.exception("couldn't read the audio output")
                if kind == "local":
                    info["urls"] = [f"http://{ip}:{CONFIG['port']}/remote" for ip in lan_ips()]
                if running_window():  # the launcher and the phone both offer Resume / Close game
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
        m = re.fullmatch(r"/audio/sbr/([\w-]+\.(mp3|ogg|wav|m4a|opus))", path)  # your SBR sound clips
        if m and (WEB / "audio" / "sbr" / m.group(1)).is_file():
            return self.send_file(WEB / "audio" / "sbr" / m.group(1), AUDIO_TYPES["." + m.group(2)])
        if path == "/audio/intro":
            f = intro_file()
            if f:
                return self.send_file(f, AUDIO_TYPES[f.suffix.lower()])
        if path in ("/icon.png", "/poster.webp", "/steelball.png"):
            return self.send_file(WEB / path[1:], "image/png" if path.endswith(".png") else "image/webp")
        m = re.fullmatch(r"/art/(\d+)(/hero)?", path)
        if m:
            f = art_file(int(m.group(1)), "hero" if m.group(2) else "poster")
            if f:
                return self.send_file(f, "image/jpeg")
        m = re.fullmatch(r"/appicon/([\w-]+)", path)
        if m:
            f = app_icon(m.group(1))
            if f:
                return self.send_file(f, "image/png")
        m = re.fullmatch(r"/media/([\w .()-]+\.(?:png|jpe?g))", unquote(path), re.I)  # a screenshot; no folders
        if m and (screenshots_dir() / m.group(1)).is_file():
            f = screenshots_dir() / m.group(1)
            return self.send_file(f, SHOT_TYPES[f.suffix.lower()])
        m = re.fullmatch(r"/img/([\w-]+)\.(jpg|png|webp)", path)  # pictures kept in web/img (e.g. GTA's art)
        if m and (WEB / "img" / f"{m.group(1)}.{m.group(2)}").is_file():
            return self.send_file(WEB / "img" / f"{m.group(1)}.{m.group(2)}",
                                  {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[m.group(2)])
        self.send_json({"error": "not found"}, 404)

    # -- POST
    def do_POST(self):
        kind = self.gate(True)
        if not kind:
            return
        if urlparse(self.path).path == "/api/padaudio" and kind == "local":  # launcher sound for the controller
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 50 * padspeaker.BLOCK_BYTES or n % padspeaker.BLOCK_BYTES:  # whole 21 ms blocks only
                return self.send_json({"error": "bad audio"}, 400)
            ok = PAD_SPEAKER.feed(self.rfile.read(n))
            return self.send_json({"ok": ok}, 200 if ok else 409)
        path, b = urlparse(self.path).path, self.body()
        try:
            if path == "/api/launch":
                # who asks (a game once started by itself at logon; this tells the TV page, phone or else apart)
                log.info("launch %s asked by %s (%s)", b, self.client_address[0], self.headers.get("User-Agent"))
                if time.time() - STARTED < 10:  # nobody picks a game this fast: a stray request, refuse it
                    return self.send_json({"error": "Couch is still starting. Try again in a few seconds."}, 409)
                before = visible_windows()
                name = launch_game(b["game"]) if "game" in b else launch_app(str(b.get("id")))
                is_game = "game" in b or any(g.get("id") == b.get("id") for g in load_games())
                RUNNING.update(name=name, windows=[], game_seen=False, is_game=is_game)
                rumble("launch")
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
                log.info("power %s asked by %s (%s)", b.get("action"), self.client_address[0], self.headers.get("User-Agent"))
                power(str(b.get("action")))
            elif path == "/api/games":
                set_choice(str(b.get("action")), str(b.get("key", "")))
            elif path == "/api/audio":
                return self.send_json({"ok": True, "name": set_audio(str(b.get("id", "")))})
            elif path == "/api/light" and kind == "local":  # the controllers' light bar: {"rgb": [r, g, b]}
                r, g, bl = (max(0, min(255, int(v))) for v in b["rgb"])
                LIGHT[0] = (r, g, bl)
            elif path == "/api/padoff":  # turn wireless controllers off (launcher menu or idle, or the phone)
                if b.get("idle") and not launcher_in_front():
                    return self.send_json({"ok": False, "off": 0})  # idle page behind a game: someone's playing
                return self.send_json({"ok": True, "off": padspeaker.turn_off()})
            elif path == "/api/volume":  # {"level": 0-100} / {"muted": bool} / {"mic": bool (muted)}
                if "level" in b:
                    audio.set_volume(level=int(b["level"]))
                if "muted" in b:
                    audio.set_volume(muted=bool(b["muted"]))
                if "mic" in b:
                    audio.set_mic_muted(bool(b["mic"]))
                return self.send_json(audio.volume_state())
            elif path == "/api/tasks":
                try:
                    task_action(int(b["id"]), str(b.get("action", "")))
                except ValueError as e:
                    return self.send_json({"error": str(e)}, 409)
            elif path == "/api/window":
                act = b.get("action")
                log.info("window: %s (from %s)", act, self.client_address[0])
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
                        close_window(h)  # same as the game's own close button
                elif act == "close-app":
                    fg = user32.GetForegroundWindow()
                    if fg and window_class(fg) not in ReturnWatcher.DESKTOP:
                        alt_f4()
                else:
                    return self.send_json({"error": "unknown action"}, 400)
            else:
                return self.send_json({"error": "not found"}, 404)
            return self.send_json({"ok": True})
        except (KeyError, ValueError, TypeError) as e:
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
    threading.Thread(target=keep_audio, daemon=True).start()
    log.info("listening on port %s; LAN: %s", port, lan_ips())
    print(f"Couch Remote on http://127.0.0.1:{port}  (phone: {', '.join(lan_ips()) or 'no LAN IP'})")
    if want_open:
        threading.Timer(0.5, open_launcher).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
