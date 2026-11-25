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
import apps_added  # noqa: E402
import audio  # noqa: E402
import bluetooth  # noqa: E402
import display  # noqa: E402
import padspeaker  # noqa: E402
import update  # noqa: E402

ROOT = Path(__file__).resolve().parent
VERSION = update.installed_sha(ROOT.parent)[:7] or "dev"  # dev: a git checkout, never auto-updated
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


def installed(entry):
    """Whether an apps.json tile belongs on this PC (one apps.json for every PC at home): an "exe" needs its program,
    a "url" a program registered for its link type, and any entry with "needs" that path. Anything else is shown."""
    needs = entry.get("needs")
    if needs and not os.path.exists(os.path.expandvars(needs)):
        return False
    target = os.path.expandvars(entry.get("target", ""))
    if entry.get("kind") == "exe" and target:
        return os.path.exists(target)
    if entry.get("kind") == "url" and ":" in target:
        scheme = target.split(":", 1)[0]
        if scheme.lower() in ("http", "https"):
            return True
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme).Close()
        except OSError:
            return False
    return True


def read_apps_file():
    """apps.json, with entries that can't make a tile (no id or name) left out. A file that doesn't parse (a typo while
    editing it) gives no built-in tiles rather than a home screen that won't load; the log says why."""
    try:
        data = json.loads(APPS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as e:
        log.error("apps.json can't be read, so its tiles are left out: %s", e)
        return {}
    ok = lambda e: isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("name"), str)
    return {**data, "apps": [a for a in data.get("apps", []) if ok(a)], "games": [g for g in data.get("games", []) if ok(g)]}


def load_apps():
    data = read_apps_file()
    apps = data.get("apps", []) + load_choices()["added"]  # yours live in choices.json: updates replace apps.json
    return [a for a in apps if installed(a)], set(int(x) for x in data.get("hide_steam_apps", []))


# ---------------------------------------------------------------- per-game display modes (□ → Display mode)
DISPLAY_TRY = [None]  # the 15 s timer of a mode being tried from the menu
BT_SEEN = []  # ids the last Bluetooth scan found: the only ones the TV may ask to pair


def bt_pair(device_id):
    if device_id not in BT_SEEN:  # only a device the last scan found, never an id sent from elsewhere
        raise ValueError("Search for the device again")
    result = bluetooth.pair(device_id)
    log.info("bluetooth pairing: %s", result)
    return result


def valid_mode(mode):
    m = tuple(int(x) for x in mode)
    if len(m) != 3 or m not in display.modes():
        raise ValueError("The TV doesn't offer that mode")
    return m


def try_mode(mode):
    """Shows a mode now; it undoes itself in 15 s unless kept, so a mode the TV can't show never strands you."""
    m = valid_mode(mode)
    if DISPLAY_TRY[0]:
        DISPLAY_TRY[0].cancel()
    if not display.apply(*m):
        raise ValueError("The TV didn't take that mode")
    DISPLAY_TRY[0] = threading.Timer(15, undo_mode)
    DISPLAY_TRY[0].start()
    log.info("trying display mode %s", display.label(*m))


def undo_mode():
    if DISPLAY_TRY[0]:
        DISPLAY_TRY[0].cancel()
        DISPLAY_TRY[0] = None
    display.restore()


def set_game_mode(key, mode=None):
    """Keeps a tried mode for a game (Couch goes back to the desktop's now; the game gets it at launch), or clears it."""
    undo_mode()
    with CHOICES_LOCK:
        c = load_choices()
        if mode:
            c["display"][key] = list(valid_mode(mode))
        else:
            c["display"].pop(key, None)
        save_choices(c)
    log.info("display mode for %s: %s", key, display.label(*mode) if mode else "the desktop's")


def game_mode_watch(started):
    """While a game launched with its own mode runs, keep it; once its window has gone (or none came within
    2 minutes), back to the desktop's mode."""
    seen = False
    while time.time() - started < 12 * 3600:
        time.sleep(2)
        if running_window():
            seen = True
        elif seen or time.time() - started > 120:
            break
    display.restore()
    log.info("game closed: display back to the desktop's mode")


def shown_apps():
    """(the Apps row in your order, without hidden ones; the hidden ones). load_apps() keeps every app, so a hidden
    app still gets its controller keys when it's opened some other way."""
    apps, c = load_apps()[0], load_choices()
    order = {app_id: i for i, app_id in enumerate(c["app_order"])}
    apps = sorted(apps, key=lambda a: order.get(a.get("id"), len(order)))  # stable: unarranged ones keep their place
    hidden = set(c["hidden_apps"])
    return [a for a in apps if a.get("id") not in hidden], [a for a in apps if a.get("id") in hidden]


def arrange_apps(action, app_id="", ids=()):
    """□ on an app tile: "order" saves the row's order (ids), "hide" and "unhide" one app."""
    known = {a.get("id") for a in load_apps()[0]}
    with CHOICES_LOCK:
        c = load_choices()
        if action == "order":
            ids = [str(i) for i in ids][:300]
            if not ids or not set(ids) <= known:
                raise ValueError("unknown app in the new order")
            c["app_order"] = ids
        elif action in ("hide", "unhide") and app_id in known:
            c["hidden_apps"] = [i for i in c["hidden_apps"] if i != app_id] + ([app_id] if action == "hide" else [])
        else:
            raise ValueError("unknown action or app")
        save_choices(c)


def add_app(kind, name, value):
    """The launcher's Add app tile. Returns the new tile's id."""
    tile = apps_added.make_tile(kind, name, value, apps_added.start_apps() if kind == "program" else [])
    with CHOICES_LOCK:
        c = load_choices()
        tile["id"] = apps_added.new_id(tile["name"], {a.get("id") for a in read_apps_file().get("apps", []) + c["added"]})
        c["added"].append(tile)
        save_choices(c)
    log.info("added app %s (%s)", tile["id"], kind)
    return tile["id"]


def remove_app(app_id):
    with CHOICES_LOCK:
        c = load_choices()
        left = [a for a in c["added"] if a.get("id") != app_id]
        if len(left) == len(c["added"]):
            raise ValueError("Only apps you added can be removed")
        c["added"] = left
        save_choices(c)
    log.info("removed app %s", app_id)


def load_games():
    """Non-Steam games from apps.json (e.g. Epic) that this PC has; their last-played time is kept in choices.json."""
    return [g for g in read_apps_file().get("games", []) if installed(g)]


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
        if not isinstance(d, dict):
            raise ValueError("not a JSON object")
    except OSError:
        d = {}  # none yet: show everything
    except ValueError as e:  # damaged (edited by hand): keep a copy before the next save replaces it
        bad = CHOICES_FILE.with_name("choices.bad.json")
        if not bad.exists():
            shutil.copyfile(CHOICES_FILE, bad)
            log.error("choices.json can't be read (%s); a copy is kept as choices.bad.json", e)
        d = {}
    return {"hidden": list(d.get("hidden", [])), "pinned": list(d.get("pinned", [])), "audio": d.get("audio"),
            "played": dict(d.get("played", {})), "took": dict(d.get("took", {})),
            "names": dict(d.get("names", {})), "art": dict(d.get("art", {})),  # your own titles and art, by game key
            "sleep_idle": int(d.get("sleep_idle", 0) or 0), "swap": bool(d.get("swap", False)),
            "added": [a for a in d.get("added", []) if isinstance(a, dict)],  # app tiles added from the launcher
            "app_order": [str(x) for x in d.get("app_order", [])],  # the Apps row as you arranged it (□ → Move)
            "hidden_apps": [str(x) for x in d.get("hidden_apps", [])],
            "display": {k: v for k, v in dict(d.get("display", {})).items() if isinstance(v, list) and len(v) == 3}}  # per-game mode


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
        g["took"] = c["took"].get(g["name"])  # seconds its window took to appear last time (the details line says it)
        if g["key"] in c["names"]:  # your own title: shown in the launcher; "name" stays the real one (Now playing)
            g["title"] = c["names"][g["key"]]
        if g["key"] in c["art"]:  # a screenshot you chose as its backdrop
            g["hero"] = c["art"][g["key"]]
        if "appid" in g:
            g["playtime"] = played.get(g["appid"], 0)
        else:  # Steam keeps its own LastPlayed; other stores' games get the time we launched them
            g["lastPlayed"] = int(c["played"].get(g["key"], 0))
    games.sort(key=lambda g: -g["lastPlayed"])  # most recently played first, across stores (stable: names stay sorted)
    shown = [g for g in games if g["key"] not in c["hidden"]]
    shown.sort(key=lambda g: c["pinned"].index(g["key"]) if g["pinned"] else len(c["pinned"]))  # stable: rest keep order
    return shown, [{"name": g.get("title", g["name"]), "key": g["key"]} for g in games if g["key"] in c["hidden"]]


def set_choice(action, key="", value=""):
    """The launcher's □ menu: hide, unhide, pin or unpin one game, rename it or give it a screenshot as art
    (an empty value puts the original back), or show every hidden game again."""
    with CHOICES_LOCK:
        c = load_choices()
        if action == "unhide-all":
            c["hidden"] = []
        elif action in ("hide", "unhide", "pin", "unpin", "rename", "art"):
            if key not in {game_key(g) for g in load_games() + steam_games()}:
                raise KeyError(key)
            if action in ("rename", "art"):
                value = str(value).strip()[:60]
                if action == "art" and value and not re.fullmatch(r"/media/[\w .()%-]+\.(png|jpe?g)", value, re.I):
                    raise ValueError("art must be one of your screenshots")
                (c["names"] if action == "rename" else c["art"]).pop(key, None)
                if value:
                    (c["names"] if action == "rename" else c["art"])[key] = value
            else:
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


STREAM = {"on": False, "device": ""}  # a Moonlight stream through Sunshine, as told by stream.cmd (Sunshine prep commands)


LAST_DEVICE = ["another screen"]  # the device the last stream went to, for a reconnect Sunshine doesn't announce


class _POWER_REASON(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("Flags", wintypes.DWORD), ("Reason", wintypes.LPWSTR)]


AWAKE = [None]  # the open power request while a stream runs


def keep_awake(on, why=""):
    """While a stream runs, the PC and its screen stay on: Moonlight's controller arrives as a virtual pad, which
    Windows' sleep timer doesn't count as input, so a long film could sleep the PC mid-stream. Shows in
    `powercfg /requests` with the reason."""
    k = ctypes.windll.kernel32
    if on and not AWAKE[0]:
        k.PowerCreateRequest.restype = wintypes.HANDLE
        h = k.PowerCreateRequest(ctypes.byref(_POWER_REASON(0, 1, why)))  # POWER_REQUEST_CONTEXT_SIMPLE_STRING
        if h and h != wintypes.HANDLE(-1).value:
            for t in (0, 1):  # PowerRequestDisplayRequired, PowerRequestSystemRequired
                k.PowerSetRequest(wintypes.HANDLE(h), t)
            AWAKE[0] = h
    elif not on and AWAKE[0]:
        for t in (0, 1):
            k.PowerClearRequest(wintypes.HANDLE(AWAKE[0]), t)
        k.CloseHandle(wintypes.HANDLE(AWAKE[0]))
        AWAKE[0] = None


def set_stream(on, device=""):
    """Sunshine says a stream started or ended. The page shows it, and the audio-keeper stands down meanwhile."""
    STREAM.update(on=bool(on), device=(device.strip() or "another screen")[:40] if on else "")
    if on:
        LAST_DEVICE[0] = STREAM["device"]
    keep_awake(bool(on), f"Streaming to {STREAM['device']}")
    log.info("stream: %s", f"on ({STREAM['device']})" if on else "off")
    emit("stream:" + (STREAM["device"] if on else "off"))
    return dict(STREAM)


SUNSHINE_LOG = Path(r"C:\Program Files\Sunshine\config\sunshine.log")


def sunshine_events(text):
    """New lines of Sunshine's log: Moonlight leaving without Quit App runs no Undo command, and rejoining a session
    that's still open runs no Do command, so the connect/disconnect lines keep the stream state right."""
    for line in text.splitlines():
        if "CLIENT DISCONNECTED" in line and STREAM["on"]:
            set_stream(False)
        elif "CLIENT CONNECTED" in line and not STREAM["on"]:
            set_stream(True, LAST_DEVICE[0])


def watch_sunshine():
    """Read Sunshine's log as it grows (read-only), from its end at start-up; a new, shorter log is read from the top."""
    pos = None
    while True:
        time.sleep(3)
        try:
            size = SUNSHINE_LOG.stat().st_size
            if pos is None or size < pos:
                pos = size if pos is None else 0
            if size > pos:
                with open(SUNSHINE_LOG, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                pos += len(chunk)
                sunshine_events(chunk.decode("utf-8", errors="ignore"))
        except OSError:
            pass  # no Sunshine (yet): keep checking


SUNSHINE_CRED = Path(__file__).resolve().parent / "cache" / "sunshine.cred"  # git-ignored (cache/)
SUNSHINE_URL = "https://localhost:47990"  # Sunshine's own page on this PC; its certificate is self-signed


class _BLOB(ctypes.Structure):
    _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]


def dpapi(data, protect):
    """Windows DPAPI: data only this Windows account on this PC can read back (used for Sunshine's login)."""
    crypt = ctypes.windll.crypt32
    src, out = _BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char))), _BLOB()
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError(ctypes.GetLastError(), "DPAPI failed")
    try:
        return ctypes.string_at(out.p, out.n)
    finally:
        kernel32.LocalFree(out.p)


def _sunshine_request(method, path, body, user_pass):
    import base64
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # localhost only, Sunshine's self-signed certificate
    req = urllib.request.Request(SUNSHINE_URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Basic " + base64.b64encode(user_pass).decode()})
    raw = urllib.request.urlopen(req, timeout=8, context=ctx).read()
    return json.loads(raw) if raw.strip() else {}


def sunshine_login(user, password):
    """Check a Sunshine login against Sunshine itself; only a working one is kept, encrypted for this Windows account."""
    import urllib.error
    pair = f"{user}:{password}".encode()
    try:
        _sunshine_request("GET", "/api/clients/list", None, pair)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False
        raise
    SUNSHINE_CRED.parent.mkdir(parents=True, exist_ok=True)
    SUNSHINE_CRED.write_bytes(dpapi(pair, protect=True))
    log.info("Sunshine login saved (encrypted)")
    return True


def sunshine_api(method, path, body=None):
    """A call to Sunshine's API with the saved login. PermissionError when there is none or Sunshine no longer
    accepts it (then it's forgotten, and the Streaming menu asks again)."""
    import urllib.error
    if not SUNSHINE_CRED.exists():
        raise PermissionError("no Sunshine login")
    try:
        return _sunshine_request(method, path, body, dpapi(SUNSHINE_CRED.read_bytes(), protect=False))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            SUNSHINE_CRED.unlink(missing_ok=True)
            log.info("Sunshine refused the saved login; forgot it")
            raise PermissionError("Sunshine login no longer works") from e
        raise


# the Streaming menu's Sunshine actions: request body from Couch -> (method, path, body) for Sunshine's API
SUNSHINE_ACTIONS = {
    "pending": lambda b={}: ("GET", "/api/pin", None),
    "clients": lambda b={}: ("GET", "/api/clients/list", None),
    "restart": lambda b={}: ("POST", "/api/restart", {}),
    "close": lambda b={}: ("POST", "/api/apps/close", {}),  # ends the session: Sunshine closes the running app (Couch)
    "pair": lambda b={}: ("POST", "/api/pin", {"pairing_id": str(b.get("pairing_id", "")), "pin": str(b.get("pin", ""))[:16],
                                               "name": str(b.get("name", ""))[:40]}),
    "unpair": lambda b={}: ("POST", "/api/clients/unpair", {"uuid": str(b.get("uuid", ""))}),
}


def parse_sc(out):
    """`sc query SunshineService` output -> "running", "stopped", or None when Sunshine isn't installed."""
    if "FAILED 1060" in out or "SERVICE_NAME" not in out:
        return None
    return "running" if "RUNNING" in out else "stopped"


def sunshine_status():
    """Sunshine (the streaming host) is a Windows service that starts with Windows; Couch only reads its state
    (starting or stopping a service needs admin)."""
    try:
        return parse_sc(subprocess.run(["sc.exe", "query", "SunshineService"], capture_output=True, text=True,
                                       timeout=5, creationflags=0x08000000).stdout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def redact(text):
    """Your user folder and name out of anything copied for support."""
    home, user = str(Path.home()), os.environ.get("USERNAME", "")
    text = text.replace(home, "%USERPROFILE%")
    return re.sub(rf"(?i)\b{re.escape(user)}\b", "<user>", text) if len(user) > 2 else text


def diagnostics():
    """About Couch (PC row): what support would ask first. Shown on the TV before anything is copied (brief 4.4)."""
    import platform

    def service(name):
        try:
            return parse_sc(subprocess.run(["sc.exe", "query", name], capture_output=True, text=True, timeout=5,
                                           creationflags=0x08000000).stdout) or "not installed"
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
    try:
        log_lines = (ROOT / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        log_lines = []
    upd = [ln for ln in log_lines if re.search(r"updated to|update \w+ skipped|update check skipped|rolled back", ln)]
    problems = [ln for ln in log_lines if " WARNING " in ln or " ERROR " in ln][-6:]
    games, _ = library()
    lines = [f"Couch {VERSION}" + (" (the main copy: it doesn't update itself)" if VERSION == "dev" else ""),
             f"Last update check: {upd[-1][:19] + ' ' + upd[-1].split(' INFO ', 1)[-1] if upd else 'none since the log started'}",
             f"Windows {platform.version()}, Python {platform.python_version()}",
             f"Streaming: Sunshine {sunshine_status() or 'not installed'}, controller driver {service('ViGEmBus')}",
             "Controllers: " + (", ".join(f"{p['name']} ({p['level']})" for p in PADS) or "none"),
             f"Apps: {len(shown_apps()[0])}, games: {len(games)}",
             "Recent problems:" + ("" if problems else " none")] + [f"  {ln}" for ln in problems]
    return [redact(ln) for ln in lines]


def audio_replaced(want, ids, names):
    """The outputs to switch away from so `want` is the default again (names), or None to leave it as is:
    a stream is on (its sound goes where Sunshine puts it), the chosen output is off (TV asleep), or Steam Remote
    Play is using its own device."""
    if STREAM["on"]:
        return None
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
user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

KEYUP, UNICODE, EXTENDED = 0x2, 0x4, 0x1
KEYS = {  # name: (virtual key, extended)
    "up": (0x26, True), "down": (0x28, True), "left": (0x25, True), "right": (0x27, True),
    "enter": (0x0D, False), "escape": (0x1B, False),
    "backspace": (0x08, False), "space": (0x20, False),
    "f13": (0x7C, False), "f14": (0x7D, False),  # no keyboard has them: an app's page script gives them a meaning
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


def key_app(exe):
    """The apps.json app with "keys" (controller button: key) whose program is exe, else {}. Stremio's own
    gamepad support never sees the controller (its WebView2 gets no gamepads), but it does follow keys."""
    return next((a for a in load_apps()[0]
                 if a.get("keys") and Path(os.path.expandvars(a["target"])).name.lower() == exe), {})


APP_DEVTOOLS = 9339  # the fixed DevTools port Couch used before 2026-11-25: a Stremio opened back then still has it


def webview_port_file(app):
    """Where a WebView2 app's browser writes the DevTools port it picked: <program>.WebView2\\EBWebView."""
    return Path(os.path.expandvars(app["target"]) + ".WebView2") / "EBWebView" / "DevToolsActivePort"


def app_devtools_port():
    """The DevTools port of the WebView2 app Couch opened (Stremio). Couch asks for port 0, so the browser picks a free
    one each time and no fixed port stays open for any local program to guess (brief 3.3); it's read from the file."""
    for a in load_apps()[0]:
        if a.get("back_closes") or a.get("page_script"):
            try:
                return int(webview_port_file(a).read_text().split()[0])
            except (OSError, ValueError, IndexError):
                pass
    return APP_DEVTOOLS


def app_page():
    """DevTools' entry for the page a WebView2 app Couch opened shows, or {} (opened some other way: no port)."""
    import urllib.request
    try:
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{app_devtools_port()}/json", timeout=2))
        return next(p for p in pages if p.get("type") == "page")
    except (OSError, ValueError, StopIteration):
        return {}


def app_page_url():
    return app_page().get("url", "")


def run_page_script(js, limit=30):
    """apps.json "page_script" (a .js file next to this one): run in the app's page every half second
    until it returns true. stremio.js loads every Board row and restyles the selection."""
    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            cdp = Cdp(app_page()["webSocketDebuggerUrl"])
            try:
                if cdp.send("Runtime.evaluate", expression=js, returnByValue=True).get("result", {}).get("value"):
                    return log.info("page script ran after %.1f s", time.time() - t0)
            finally:
                cdp.s.close()
        except (OSError, KeyError, RuntimeError, ConnectionError):
            pass  # not up yet
        time.sleep(0.5)
    log.info("page script never ran")


FITTING = [False]  # a fit_page_to_screen() session is holding the app's page size


def fit_page_to_screen(limit=30):
    """Stremio won't lay its page out narrower than 1366 px, but a 4K TV at 300% scaling is 1280 px wide, so its right
    edge (player buttons, side panels) was off screen. Tells the page the screen's real size, and keeps this DevTools
    session open while the app runs: the size override ends with the session."""
    if FITTING[0]:
        return
    FITTING[0] = True
    try:
        t0 = time.time()
        while time.time() - t0 < limit:
            try:
                cdp = Cdp(app_page()["webSocketDebuggerUrl"])
            except (OSError, KeyError, ConnectionError):
                time.sleep(0.5)
                continue
            try:
                w, h, inner = cdp.send("Runtime.evaluate", expression="[screen.width, screen.height, innerWidth]",
                                       returnByValue=True)["result"]["value"]
                if inner <= w:
                    return  # it fits already (a smaller scale, or a wider screen)
                cdp.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=0, mobile=False)
                log.info("fitted the app's page to the screen: %s px wide, not %s", w, inner)
                cdp.s.settimeout(None)
                while cdp.s.recv(4096):  # until the app closes
                    pass
                return
            except (OSError, KeyError, RuntimeError, ConnectionError, TypeError, ValueError):
                time.sleep(0.5)
            finally:
                cdp.s.close()
    finally:
        FITTING[0] = False


def back_or_close(h, key, first_screen):
    """apps.json "back_closes": like a TV, ○ on an app's first screen (its address matches that pattern)
    closes it; Stremio has no way out of its own. Anywhere else ○ is its back key."""
    if not re.search(first_screen, app_page_url()):
        return press(key)
    if user32.GetForegroundWindow() == h:
        log.info("back on %s's first screen; closing it", window_exe(h))
        user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(1)
        open_launcher()  # Windows would put whatever was behind in front


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


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("rc", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


def borderless_fullscreen(h):
    """An app that opens in a normal window (Stremio) fills the TV with no title bar or frame, as a game does."""
    # Real pixels: DPI-scaled sizes round (4096 px came out 4095), and a window a pixel short of the
    # screen isn't full screen to Windows, so the taskbar stays on top of it.
    old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    try:
        style = user32.GetWindowLongW(h, -16)  # GWL_STYLE
        user32.SetWindowLongW(h, -16, style & ~0x00CF0000)  # no caption, frame, system menu, min/max boxes
        mi = _MONITORINFO(cb=ctypes.sizeof(_MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromWindow(h, 2), ctypes.byref(mi))  # MONITOR_DEFAULTTONEAREST
        r = mi.rc
        # a pixel short first: a window that already had the screen's size gets no resize from the frame going,
        # and Stremio then leaves its page at the framed size (a grey strip along the bottom)
        for short in (1, 0):
            user32.SetWindowPos(h, None, r.left, r.top, r.right - r.left, r.bottom - r.top - short, 0x0020 | 0x0040)  # FRAMECHANGED|SHOWWINDOW
        user32.SetCursorPos(r.right - 1, r.bottom - 1)  # pointer to the corner: resting on a poster it shows a tooltip
    finally:
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


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
    banner). Edge must not be running on the profile. Before its first run there is no file yet: a new one holding just
    this setting is enough, and Edge fills in the rest."""
    prefs = PROFILES / profile / "Default" / "Preferences"
    try:
        prefs.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(prefs.read_text(encoding="utf-8")) if prefs.exists() else {}
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
    elif action == "close":
        close_window(h)
    elif action == "force":
        cmd = ["taskkill", "/IM", "steam.exe", "/T", "/F"] if steam else ["taskkill", "/PID", str(window_pid(h)), "/T", "/F"]
        subprocess.run(cmd, capture_output=True, creationflags=0x08000000)
    else:
        raise ValueError(f"unknown action {action!r}")


def close_window(h):
    """What the window's own X button does (WM_SYSCOMMAND SC_CLOSE), so apps can still ask to save. Steam's own
    windows (Big Picture, the Steam window) only go to the tray that way, so quit Steam itself instead."""
    if window_exe(h) in ("steamwebhelper.exe", "steam.exe"):
        log.info("closing Steam (steam://exit)")
        return open_url("steam://exit")
    user32.PostMessageW(h, 0x0112, 0xF060, 0)


def running_window():
    """The launched game/app's window while it's still open, else None."""
    alive = [(h, window_exe(h)) for h in RUNNING["windows"] if user32.IsWindow(h) and user32.IsWindowVisible(h)]
    return pick_running(alive, RUNNING.get("game_seen", False))


def started_after(h, t):
    """Whether window h's program started after time t (True if Windows won't say)."""
    ph = kernel32.OpenProcess(0x1000, False, window_pid(h))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not ph:
        return True
    try:
        made, x1, x2, x3 = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if not kernel32.GetProcessTimes(ph, *(ctypes.byref(f) for f in (made, x1, x2, x3))):
            return True
        return (made.hi << 32 | made.lo) / 1e7 - 11644473600 > t  # FILETIME counts 100 ns from 1601
    finally:
        kernel32.CloseHandle(ph)


def keep_behind(exe, is_game, game_seen):
    """While a game starts, its store launchers (not Steam's) stay behind Couch: covered, never minimized, since a
    minimized Rockstar launcher hung every GTA launch (2026-11-22)."""
    return is_game and not game_seen and exe in LAUNCHER_EXES - {"steam.exe", "steamwebhelper.exe"}


def focus_what_opens(before):
    """Windows won't give focus to a window our background process started (Steam, a game...), so the
    controller wouldn't reach it. Focus each new window as it appears. The windows are also remembered for
    Resume / Close game, so keep watching until the game's own window shows up: store launchers (Epic, then
    Rockstar's) come first, and the game can take minutes. Stop 10 s after a game window, or after 3 minutes.
    Store launchers stay behind Couch (keep_behind); one still asking to sign in after 15 s comes forward, and if no
    game window shows within 90 s the newest one does (it may want an update or a click)."""
    seen, last, t0, name = set(before), 0.0, time.time(), RUNNING["name"]
    # store-launcher window -> since when Couch covers it (already-open ones too: Rockstar's comes forward when the
    # game starts); None once Couch stops covering for this launch
    behind = {h: t0 for h in before if keep_behind(window_exe(h), RUNNING.get("is_game"), False)}
    # its tile pressed while it's already open (Stremio allows one copy, so no new window comes): bring that one back
    mine = [h for h in before if RUNNING.get("exe") and window_exe(h) == RUNNING["exe"]]
    if mine:
        RUNNING["windows"] += mine
        if RUNNING.get("fullscreen"):
            borderless_fullscreen(mine[0])
        focus_window(mine[0])
        return
    while time.time() - t0 < 180 and RUNNING["name"] == name:  # a newer launch takes over
        time.sleep(0.5)
        if behind:
            for h, since in list(behind.items()):
                if time.time() - since > 15 and re.search(r"sign.?in|log.?in", window_title(h), re.I):
                    log.info("%s is asking to sign in; showing it", window_exe(h))
                    focus_window(h)
                    del behind[h]
            if behind and not last and time.time() - t0 > 90:
                h = max(behind, key=behind.get)
                log.info("no game window after 90 s; showing %s", window_exe(h))
                focus_window(h)
                behind = None
            elif behind and not last and user32.GetForegroundWindow() in behind and find_launcher():
                focus_window(find_launcher())  # a launcher took the screen by itself: cover it again
        new = [h for h in visible_windows() if h not in seen]
        seen.update(new)
        if RUNNING.get("is_game"):  # an app that was already running (Claude opening after login) isn't the game
            new = [h for h in new if window_exe(h) in LAUNCHER_EXES or started_after(h, t0 - 2)]
        if new:
            RUNNING["windows"] += new
            time.sleep(0.3)  # let it finish appearing
            hide = [h for h in new if behind is not None and keep_behind(window_exe(h), RUNNING.get("is_game"), last)]
            show = [h for h in new if h not in hide]
            for h in hide:
                behind[h] = time.time()
            if show:
                if RUNNING.get("fullscreen"):  # apps.json "fullscreen": true (Stremio opens in a normal window)
                    borderless_fullscreen(show[0])
                focus_window(show[0])
            elif find_launcher():
                focus_window(find_launcher())
            if any(window_exe(h) not in LAUNCHER_EXES for h in new):
                if not last:  # how long a launch takes from the press; the Starting screen shows it next time
                    took = time.time() - t0
                    log.info("%s window after %.0f s (%s)", name, took,
                             next(window_exe(h) for h in new if window_exe(h) not in LAUNCHER_EXES))
                    with CHOICES_LOCK:
                        c = load_choices()
                        c["took"][name] = int(round(took / 5) * 5) or 5  # "about": to the nearest 5 s
                        save_choices(c)
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


def msix_logo(args):
    """The biggest square logo of a Store (MSIX) app launched through shell:AppsFolder, or None.
    The package folder carries the version, so it is found by pattern each time."""
    for a in args:
        m = re.fullmatch(r"shell:AppsFolder\\([\w.-]+)_(\w+)!.*", str(a), re.I)  # names can have dots: Microsoft.WindowsNotepad
        if m:
            # WindowsApps can't be listed without admin, but the package's own folder can be read: the registry names it
            repo = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
            logos = []
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, repo) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    name = winreg.EnumKey(k, i)
                    if name.startswith(m[1] + "_") and name.endswith("__" + m[2]):
                        with winreg.OpenKey(k, name) as pk:
                            assets = Path(winreg.QueryValueEx(pk, "PackageRootFolder")[0]) / "assets"
                            logos = [*assets.glob("Square*Logo*.png"), *assets.glob("*AppList*.png")]  # Notepad: NotepadAppList
            best = [p for p in logos if p.name == "Square44x44Logo.targetsize-256.png" or p.name.endswith("AppList.targetsize-256.png")]
            return (best or sorted(logos, key=lambda p: p.stat().st_size)[-1:] or [None])[0]
    return None


def manifest_icon(manifest, base):
    """URL of the largest plain ("any") icon in a web app manifest (already parsed), or None."""
    from urllib.parse import urljoin
    best, best_px = None, 0
    for ic in manifest.get("icons", []):
        px = int(m[1]) if (m := re.match(r"(\d+)x", str(ic.get("sizes", "")))) else 0
        if "any" in ic.get("purpose", "any").split() and px > best_px and ic.get("src"):
            best, best_px = urljoin(base, ic["src"]), px
    return best


def web_icon_png(url, out):
    """Save a site's icon as a PNG: its apple-touch-icon, else the biggest icon in its web manifest. False if none.
    shortcut: stdlib only and no retry; some sites (claude.ai) block scripts and give just the apple-touch-icon."""
    import urllib.request
    from urllib.parse import urljoin

    def get(u, limit=2_000_000):
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 Couch"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read(limit)

    def save(u):
        import io
        import pygame
        pygame.image.save(pygame.image.load(io.BytesIO(get(u))), str(out))  # a bad image raises: caller moves on
        return True

    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}/"
    try:
        return save(urljoin(origin, "apple-touch-icon.png"))
    except Exception:
        pass
    try:
        m = re.search(rb'<link[^>]+rel=["\']manifest["\'][^>]*href=["\']([^"\']+)', get(origin, 500_000), re.I) \
            or re.search(rb'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']manifest', get(origin, 500_000), re.I)
        murl = urljoin(origin, m[1].decode()) if m else urljoin(origin, "manifest.webmanifest")
        icon = manifest_icon(json.loads(get(murl)), murl)
        return bool(icon) and save(icon)
    except Exception as e:
        log.info("no web icon for %s: %s", origin, e)
        return False


def app_icon(app_id):
    """PNG of an app tile's icon, or None. Order: a PNG dropped in cache/icons (your own override, kept), the
    program's own icon (redone when the app updates), a Store app's package logo, a website's icon. A failed
    lookup is remembered for an hour (<id>.none) so an offline PC doesn't retry on every tile."""
    apps, _ = load_apps()
    app = next((a for a in apps if a.get("id") == app_id), None)
    if not app:
        return None
    target = os.path.expandvars(app.get("target", ""))
    exe = Path(target) if app.get("kind") == "exe" else steam_path() / "steam.exe" if target.startswith("steam:") else None
    out, none = ICON_CACHE / f"{app_id}.png", ICON_CACHE / f"{app_id}.none"
    if exe and exe.exists() and exe.name.lower() != "explorer.exe":
        with ICON_LOCK:
            if not out.exists() or out.stat().st_mtime < exe.stat().st_mtime:
                ICON_CACHE.mkdir(parents=True, exist_ok=True)
                if not exe_icon_png(exe, out):
                    return None
        return out
    with ICON_LOCK:
        if out.exists():
            return out
        if none.exists() and time.time() - none.stat().st_mtime < 3600:
            return None
        ICON_CACHE.mkdir(parents=True, exist_ok=True)
        logo = msix_logo(app.get("args", []))
        if logo:
            shutil.copyfile(logo, out)
            return out
        if target.startswith("http") and web_icon_png(target, out):
            return out
        none.touch()
    return None


# ---------------------------------------------------------------- controller
# The server reads the controller itself (through SDL, via pygame), so it works whether or not
# Steam is running. Presses only go to the launcher page while the launcher is in front.

LISTENERS = []  # one queue per open launcher page
LISTENERS_LOCK = threading.Lock()
PAD_STATUS = "pad:none"  # last controller/battery state sent to the launcher; new pages get it on connect
PADS = []  # [{"name", "level"}] of the connected controllers, as the controller loop last saw them
# True once the server reads the controller, False if it can't (then the page uses the Gamepad API).
# None while it's still starting: the page must not fall back then, or both read the pad (seen at logon).
PAD_READER = None
SWAP = [load_choices()["swap"]]  # ✕ and ○ swapped, set in the launcher's Controls menu
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


WEATHER = {"at": 0.0, "place": None, "now": None}
WEATHER_LOCK = threading.Lock()


def weather():
    """Current weather for config.json's "weather": {"city": ..., "unit": "fahrenheit" | "celsius"}, from Open-Meteo
    (free, no account), refreshed at most every 30 min. None when no city is set (then nothing is sent anywhere) or
    it can't be reached; the last good reading stays meanwhile."""
    cfg = CONFIG.get("weather") or {}
    if not cfg.get("city"):
        return None
    with WEATHER_LOCK:
        if time.time() - WEATHER["at"] < 1800:
            return WEATHER["now"]
        WEATHER["at"] = time.time()
        import urllib.request
        from urllib.parse import quote
        get = lambda url: json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Couch"}), timeout=6))
        try:
            if not WEATHER["place"]:
                WEATHER["place"] = get(f"https://geocoding-api.open-meteo.com/v1/search?count=1&name={quote(cfg['city'])}")["results"][0]
            pl, unit = WEATHER["place"], "celsius" if cfg.get("unit") == "celsius" else "fahrenheit"
            w = get(f"https://api.open-meteo.com/v1/forecast?latitude={pl['latitude']}&longitude={pl['longitude']}"
                    f"&current=temperature_2m,weather_code,is_day&daily=temperature_2m_max,temperature_2m_min"
                    f"&temperature_unit={unit}&timezone=auto&forecast_days=1")
            c, d = w["current"], w["daily"]
            WEATHER["now"] = {"city": pl["name"], "temp": round(c["temperature_2m"]), "code": int(c["weather_code"]),
                              "day": bool(c["is_day"]), "hi": round(d["temperature_2m_max"][0]),
                              "lo": round(d["temperature_2m_min"][0])}
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            log.info("weather unavailable: %s", e)
        return WEATHER["now"]


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


def parse_wlan(out):
    """`netsh wlan show interfaces` -> {"kind": "wifi", "signal": %, "name": ssid} when on Wi-Fi, else wired.
    shortcut: English field names; on another Windows language it says wired. Match the localized labels if needed."""
    state = re.search(r"^\s*State\s*:\s*(\w+)", out, re.M)
    signal = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out, re.M)
    if state and state.group(1).lower() == "connected" and signal:
        return {"kind": "wifi", "signal": int(signal.group(1)), "name": ssid.group(1) if ssid else ""}
    return {"kind": "wired"}


def network():
    """How the PC is connected, for the Streaming menu: Moonlight's picture depends on it."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    return parse_wlan(out)


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


def sdl_power_level(n):
    """SDL_JoystickPowerLevel -> the names pygame uses (-1 unknown ... 5 max)."""
    return {0: "empty", 1: "low", 2: "medium", 3: "full", 4: "wired", 5: "max"}.get(n, "unknown")


def pad_status_for(levels, charging=()):
    """pad:none, or each controller's battery from SDL power levels, comma-separated (the launcher shows one each);
    a level ending in + is on charge."""
    order = ["empty", "low", "medium", "full", "max", "wired"]
    levels = [(lv if lv in order else "max") + ("+" if i in charging else "") for i, lv in enumerate(levels)]  # "unknown": don't alarm anyone
    return "pad:" + (",".join(levels) if levels else "none")


def dualsense_charging():
    """True/False: is the Bluetooth DualSense on charge. SDL gives only the level, but the pad's own full report
    (0x31, which SDL has switched it to once it has rumbled it) carries a status byte: high nibble 1 = charging.
    None if there is no such pad or no report. shortcut: first Sony HID device only, so two Bluetooth DualSenses
    would share one answer; revisit if you ever pair two."""
    k, hid, sa = ctypes.windll.kernel32, ctypes.windll.hid, ctypes.windll.setupapi
    k.CreateFileW.restype = sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p

    class Guid(ctypes.Structure):
        _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    class Iface(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("g", Guid), ("f", ctypes.c_ulong), ("r", ctypes.c_void_p)]

    class Over(ctypes.Structure):
        _fields_ = [("a", ctypes.c_void_p), ("b", ctypes.c_void_p), ("o", ctypes.c_ulong * 2), ("e", ctypes.c_void_p)]

    g = Guid()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    devs = ctypes.c_void_p(sa.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12))  # present interfaces
    i = 0
    while True:
        d = Iface()
        d.cb = ctypes.sizeof(Iface)
        if not sa.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(g), i, ctypes.byref(d)):
            return None
        i += 1
        n = wintypes.DWORD()
        sa.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(d), None, 0, ctypes.byref(n), None)
        buf = ctypes.create_string_buffer(n.value)
        ctypes.c_ulong.from_buffer(buf).value = 8  # cbSize of the 64-bit detail struct
        sa.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(d), buf, n, None, None)
        path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
        if "054c" not in path.lower() or "pid&0ce6" not in path.lower() and "pid_0ce6" not in path.lower():
            continue
        f = k.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)  # read+write, shared, overlapped
        if f in (None, ctypes.c_void_p(-1).value):
            continue
        f, out, ov = ctypes.c_void_p(f), ctypes.create_string_buffer(100), Over()
        ov.e = k.CreateEventW(None, 1, 0, None)
        try:
            k.ReadFile(f, out, 100, None, ctypes.byref(ov))
            if k.WaitForSingleObject(ctypes.c_void_p(ov.e), 300) != 0:
                k.CancelIoEx(f, ctypes.byref(ov))
                return None
            got = wintypes.DWORD()
            k.GetOverlappedResult(f, ctypes.byref(ov), ctypes.byref(got), 0)
            return out.raw[54] >> 4 == 1 if got.value > 54 and out.raw[0] == 0x31 else None
        finally:
            k.CloseHandle(ctypes.c_void_p(ov.e))
            k.CloseHandle(f)


def launcher_in_front():
    fg = user32.GetForegroundWindow()
    return bool(fg) and window_title(fg).startswith(LAUNCHER_TITLE)


REMOTE_PAD = {"up": "up", "down": "down", "left": "left", "right": "right", "enter": "a", "escape": "b"}


def remote_key(key):
    """A phone-remote key. In Couch and in apps with their own controller keys it acts as the controller button would:
    Couch ignores keyboard copies of pad keys once a controller has been used, and Stremio's Back isn't Escape."""
    action = REMOTE_PAD.get(key)
    if action and launcher_in_front():
        return emit(action)
    fg = user32.GetForegroundWindow()
    app = key_app(window_exe(fg))
    if action == "b" and app.get("back_closes"):
        return threading.Thread(target=back_or_close, args=(fg, app["keys"]["b"], app["back_closes"]), daemon=True).start()
    press(app.get("keys", {}).get(action) or key)


def exe_running(name):
    out = subprocess.run(["tasklist", "/fi", f"imagename eq {name}", "/nh"], capture_output=True,
                         text=True, creationflags=0x08000000).stdout
    return name.lower() in out.lower()


EPIC_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "EpicGamesLauncher/Saved/Logs/EpicGamesLauncher.log"
ROCKSTAR_EXE = r"C:\Program Files\Rockstar Games\Launcher\Launcher.exe"
ROCKSTAR_LOG = Path(os.environ.get("USERPROFILE", "")) / "Documents/Rockstar Games/Launcher/launcher.log"


def warm_rockstar():
    """At login, start Rockstar's launcher so a GTA press skips its startup and sign-in (Epic starts itself at login
    already). Its window stays behind Couch for 90 s (covered, never minimized); a sign-in it asks for is left until
    a GTA press, whose launch shows it after 15 s."""
    if exe_running("Launcher.exe") or not Path(ROCKSTAR_EXE).exists():
        return
    if not any(a.get("rockstar") for a in load_apps()[0]):  # no Rockstar game on this PC: nothing to warm up for
        return
    log.info("starting Rockstar's launcher in the background")
    subprocess.Popen([ROCKSTAR_EXE], cwd=str(Path(ROCKSTAR_EXE).parent), creationflags=0x00000008 | 0x00000200)
    t0, name = time.time(), RUNNING["name"]
    while time.time() - t0 < 90 and RUNNING["name"] == name:  # a launch takes over covering
        time.sleep(0.5)
        fg = user32.GetForegroundWindow()
        if window_exe(fg) in ("socialclubhelper.exe", "launcher.exe") and find_launcher():
            focus_window(find_launcher())


def start_then(cmd, log_file, signed_in, then, limit):
    """Starts a closed store launcher, waits until its log shows `signed_in`, then calls then(). Games launch reliably
    only with their launchers already up and signed in (Epic ignores a link while it starts from closed; GTA ran when
    Epic and Rockstar were both open; 2026-11-22). After `limit` seconds, then() runs anyway."""
    t0, name = time.time(), Path(cmd[0]).name
    subprocess.Popen(cmd, cwd=str(Path(cmd[0]).parent), creationflags=0x00000008 | 0x00000200)
    while time.time() - t0 < limit:
        time.sleep(0.5)
        try:  # both launchers start a fresh log each run, so only a log written after t0 counts
            if log_file.stat().st_mtime > t0 and signed_in in log_file.read_text(errors="ignore"):
                log.info("%s started and signed in after %.0f s", name, time.time() - t0)
                break
        except OSError:
            pass
    else:
        log.info("%s didn't report signing in within %d s; going on anyway", name, limit)
    then()


def repeat_gap(n, in_couch):
    """Seconds to the next repeat of a held direction, after n repeats. In other apps (Stremio's 37-row Board)
    it speeds up as it is held, as on a PS5: 9 moves a second at first, 25 within a second. Couch's own
    rows keep a steady pace for their animations."""
    return 0.11 if in_couch else max(0.04, 0.11 - 0.01 * n)


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
    # battery and rumble go through SDL too, looking each controller up by id every time: pygame's Controller
    # objects crashed the server (access violation, 2026-11-22) once a Bluetooth pad was dropped and came back
    sdl.SDL_GameControllerGetJoystick.argtypes, sdl.SDL_GameControllerGetJoystick.restype = (ctypes.c_void_p,), ctypes.c_void_p
    sdl.SDL_JoystickCurrentPowerLevel.argtypes, sdl.SDL_JoystickCurrentPowerLevel.restype = (ctypes.c_void_p,), ctypes.c_int
    sdl.SDL_GameControllerName.argtypes, sdl.SDL_GameControllerName.restype = (ctypes.c_void_p,), ctypes.c_char_p
    sdl.SDL_GameControllerRumble.argtypes = (ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32)
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
    pulled = set()  # L2/R2 held past halfway: one press each pull
    dpad = set()
    log.info("controller support on")
    PAD_READER = True
    next_status = 0.0

    def live():  # SDL's own handles for the controllers still open; a dropped one is simply not there
        return [p for p in map(sdl.SDL_GameControllerFromInstanceID, pads) if p]

    def pad_status():
        ps = live()
        levels = [sdl_power_level(sdl.SDL_JoystickCurrentPowerLevel(sdl.SDL_GameControllerGetJoystick(p))) for p in ps]
        PADS[:] = [{"name": (sdl.SDL_GameControllerName(p) or b"Controller").decode(errors="replace"), "level": lv}
                   for p, lv in zip(ps, levels)]  # for the Controls screen
        sony = [i for i, p in enumerate(ps) if b"DualSense" in (sdl.SDL_GameControllerName(p) or b"")]
        return pad_status_for(levels, sony if sony and levels[sony[0]] != "wired" and dualsense_charging() else ())

    added = [0.0]  # when a controller last connected

    def act(action):
        LAST_PAD[0] = time.time()
        if SWAP[0] and action in ("a", "b"):  # ✕ and ○ swapped (Controls menu): in the launcher and apps alike
            action = "b" if action == "a" else "a"
        if action == "create":  # anywhere, in games too
            if time.time() - added[0] < 3:  # a streamed (virtual) pad reports Back as it connects: not a press
                return log.info("ignored Create right after a controller connected")
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
        elif action in (app := key_app(window_exe(fg := user32.GetForegroundWindow()))).get("keys", {}):
            if action == "b" and app.get("back_closes"):
                threading.Thread(target=back_or_close, args=(fg, app["keys"]["b"], app["back_closes"]),
                                 daemon=True).start()
            else:
                press(app["keys"][action])

    while True:
        for e in pygame.event.get():
            if e.type == B.CONTROLLERDEVICEADDED:
                try:
                    c = gc.Controller(e.device_index)
                    pads[c.as_joystick().get_instance_id()] = c
                    added[0] = time.time()
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
                elif e.axis in (B.CONTROLLER_AXIS_TRIGGERLEFT, B.CONTROLLER_AXIS_TRIGGERRIGHT):
                    t = "l2" if e.axis == B.CONTROLLER_AXIS_TRIGGERLEFT else "r2"
                    if e.value > 20000 and t not in pulled:
                        pulled.add(t)
                        act(t)
                    elif e.value < 8000:
                        pulled.discard(t)
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
                for p in live():
                    sdl.SDL_GameControllerRumble(p, int(lo * 65535), int(hi * 65535), int(ms))
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
                held[d] = [now + 0.38, 0]  # next repeat, repeats so far
                act(d)
            elif now >= held[d][0]:
                held[d][1] += 1
                held[d][0] = now + repeat_gap(held[d][1], launcher_in_front())
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

    def send_link():
        try:
            subprocess.Popen([exe] + args, cwd=str(Path(exe).parent), creationflags=0x00000008 | 0x00000200)
        except OSError as e:  # e.g. Steam set to run as administrator (WinError 740): Windows' own way handles that
            log.info("opening %s link directly failed (%s); using Windows' handler", scheme, e)
            return os.startfile(url)
        log.info("opened %s link with %s", scheme, Path(exe).name)

    if url.startswith("steam://open/bigpicture") and not exe_running("steam.exe"):  # a closed Steam drops the link
        log.info("Steam is closed; starting it in Big Picture")
        return subprocess.Popen([exe, "-gamepadui"], cwd=str(Path(exe).parent), creationflags=0x00000008 | 0x00000200)
    if scheme == "com.epicgames.launcher" and not exe_running("EpicGamesLauncher.exe"):
        log.info("Epic is closed; starting it before sending the link")
        return threading.Thread(target=start_then, args=([exe, "-silent"], EPIC_LOG, "OnLoginComplete", send_link, 30),
                                daemon=True).start()
    send_link()


def launch_app(app_id):
    apps, _ = load_apps()
    app = next((a for a in apps + load_games() if a.get("id") == app_id), None)
    if not app:
        raise KeyError(app_id)
    kind, target = app.get("kind"), os.path.expandvars(app.get("target", ""))
    if kind == "url" and app.get("rockstar") and not exe_running("Launcher.exe"):
        # shortcut: any program named Launcher.exe counts as Rockstar's; make this check the path if one ever clashes
        log.info("Rockstar's launcher is closed; starting it before %s", app["name"])
        threading.Thread(target=start_then, args=([ROCKSTAR_EXE], ROCKSTAR_LOG, "is now signed in",
                                                  lambda: open_url(target), 60), daemon=True).start()
    elif kind == "url":
        open_url(target)
    elif kind == "exe":
        env = None
        if app.get("back_closes") or app.get("page_script"):  # a WebView2 app (Stremio): DevTools reach its page
            if not exe_running(Path(target).name):  # a fresh start writes a new port file; an old one would mislead
                webview_port_file(app).unlink(missing_ok=True)
            env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=0")
        subprocess.Popen([target] + list(app.get("args", [])), cwd=str(Path(target).parent), env=env,
                         creationflags=0x00000008 | 0x00000200)
        if app.get("page_script"):
            js = (ROOT / app["page_script"]).read_text(encoding="utf-8")
            threading.Thread(target=run_page_script, args=(js,), daemon=True).start()
            threading.Thread(target=fit_page_to_screen, daemon=True).start()
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


SLEEP = {"at": 0}  # the sleep timer: when to sleep (0: off). The idle rule lives in choices.json ("sleep_idle", minutes)
LAST_PAD = [time.time()]  # the controller's last press: Windows' own idle time doesn't count controllers


class _LASTINPUT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    """Seconds since the last keyboard, mouse or controller input."""
    li = _LASTINPUT(ctypes.sizeof(_LASTINPUT), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    since_keys = ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000
    return min(since_keys, time.time() - LAST_PAD[0])


def sleep_due(now, idle, idle_rule, streaming, game_running):
    """The sleep timer ran out, or (idle rule) nobody has touched anything for that long and nothing is playing."""
    return bool(SLEEP["at"] and now >= SLEEP["at"]) or \
        bool(idle_rule and idle >= idle_rule * 60 and not streaming and not game_running)


RESTART = 75  # exit code that asks the supervisor (see the bottom of this file) to start the new version


def restart_couch():
    """Ends this server; the supervisor starts the updated one straight away. The TV page notices the new version
    and reloads itself."""
    log.info("restarting for the update")
    logging.shutdown()
    os._exit(RESTART)


def supervise(run_child, root=ROOT.parent):
    """The process the "Couch Launcher" task starts: runs Couch as a child, again after it updates itself (a
    task-started process that exits can't reliably start the next one: the restarted server never came up in Windows
    Sandbox, 2026-11-24), on the old files if the updated one crashes within 2 minutes, and again after any other
    crash, unless it crashed 3 times in 10 minutes (then something's wrong that a restart won't fix)."""
    updated, crashes = False, []
    while True:
        t0 = time.time()
        rc = run_child()
        if rc == RESTART:
            updated = True
        elif updated and rc != 0 and time.time() - t0 < 120 and update.rollback(root):
            updated = False  # shortcut: a crash that isn't the update's fault (2 min window) also rolls back
        elif rc != 0:
            now = time.time()
            crashes = [t for t in crashes if now - t < 600] + [now]
            if len(crashes) >= 3:
                return rc
            time.sleep(3)
        else:
            return rc


def update_watch():
    """Every 6 hours, while nothing is playing or streaming and nobody has touched the PC for 30 minutes."""
    while True:
        time.sleep(6 * 3600)
        if not running_window() and not STREAM["on"] and idle_seconds() > 1800 and update.check(ROOT.parent):
            restart_couch()


def sleep_watch():
    last = time.time()
    while True:
        time.sleep(30)
        now = time.time()
        if now - last > 120:  # the PC was asleep: waking it is the newest input (the power button isn't one)
            LAST_PAD[0] = now
        last = now
        if sleep_due(now, idle_seconds(), load_choices().get("sleep_idle", 0), STREAM["on"], bool(running_window())):
            log.info("sleep: %s", "timer" if SLEEP["at"] and now >= SLEEP["at"] else "idle")
            SLEEP["at"] = 0
            power("sleep")


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
            if path == "/api/weather":
                return self.send_json({"weather": weather()})
            if path == "/api/storage":
                return self.send_json({"drives": fixed_drives()})
            if path == "/api/media":
                return self.send_json({"shots": media_list()})
            if path == "/api/network":
                return self.send_json(network())
            if path == "/api/bluetooth" and kind == "local":  # PC row → Bluetooth
                return self.send_json({"available": bluetooth.available(),
                                       "paired": bluetooth.paired() if bluetooth.available() else []})
            if path == "/api/display" and kind == "local":  # □ → Display mode: what the TV offers, and each game's
                return self.send_json({"now": list(display.current()), "saved": load_choices()["display"],
                                       "modes": [{"mode": list(m), "label": display.label(*m)}
                                                 for m in display.choices(display.modes(), display.current())]})
            if path == "/api/diagnostics" and kind == "local":  # About Couch on the TV
                return self.send_json({"lines": diagnostics()})
            if path == "/api/startapps":  # the Add app tile's list of programs
                return self.send_json({"apps": [{"name": n, "id": i} for n, i in apps_added.start_apps()]})
            if path == "/api/running":  # cheap: the launcher polls it to keep Now playing current
                return self.send_json({"running": {"name": RUNNING["name"]} if running_window() else None,
                                       "version": VERSION})
            if path == "/api/info":
                apps, hidden_apps = shown_apps()
                games, hidden = library()
                info = {"name": socket.gethostname(), "apps": apps, "games": games, "hidden": hidden,
                        "hiddenApps": [{"id": a["id"], "name": a["name"]} for a in hidden_apps], "pads": list(PADS),
                        "padReader": PAD_READER, "intro": bool(intro_file()), "sounds": sound_clips(),
                        "stream": STREAM["device"] if STREAM["on"] else None, "sunshine": sunshine_status(),
                        "sunshineLogin": SUNSHINE_CRED.exists(), "sleepAt": int(SLEEP["at"]),
                        "sleepIdle": load_choices()["sleep_idle"], "swap": SWAP[0], "version": VERSION,
                        "installerChanged": (ROOT / "cache" / "installer-changed").exists()}
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
                is_game = "game" in b or any(g.get("id") == b.get("id") for g in load_games())
                mode = is_game and load_choices()["display"].get(f"steam:{int(b['game'])}" if "game" in b else str(b.get("id")))
                if mode and display.current() != tuple(mode) and display.apply(*mode):  # the game's own mode, before it opens
                    log.info("display mode for this game: %s", display.label(*mode))
                    threading.Thread(target=game_mode_watch, args=(time.time(),), daemon=True).start()
                name = launch_game(b["game"]) if "game" in b else launch_app(str(b.get("id")))
                app = next((a for a in load_apps()[0] if a.get("id") == b.get("id")), {})
                fullscreen = bool(app.get("fullscreen"))
                exe = Path(os.path.expandvars(app["target"])).name.lower() if app.get("kind") == "exe" else ""
                RUNNING.update(name=name, windows=[], game_seen=False, is_game=is_game, fullscreen=fullscreen, exe=exe)
                rumble("launch")
                threading.Thread(target=focus_what_opens, args=(before,), daemon=True).start()
                WATCHER.arm()
                return self.send_json({"ok": True, "name": name, "took": load_choices()["took"].get(name)})
            if path == "/api/key":
                if b.get("key") not in KEYS:
                    return self.send_json({"error": "unknown key"}, 400)
                remote_key(b["key"])
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
                a = str(b.get("action"))
                if a == "timer":  # {"minutes": n}: sleep in n minutes, 0 cancels
                    SLEEP["at"] = time.time() + 60 * max(0, min(600, int(b.get("minutes", 0)))) if b.get("minutes") else 0
                elif a == "idle":  # {"minutes": n}: sleep after n minutes untouched with nothing playing, 0 off
                    with CHOICES_LOCK:
                        c = load_choices()
                        c["sleep_idle"] = max(0, min(600, int(b.get("minutes", 0))))
                        save_choices(c)
                else:
                    power(a)
            elif path == "/api/bluetooth" and kind == "local":  # {"action": "scan"} (12 s) or {"action": "pair", "id"}
                if b.get("action") == "scan":
                    devices = bluetooth.scan()
                    BT_SEEN[:] = [d["id"] for d in devices]
                    return self.send_json({"ok": True, "devices": devices})
                if b.get("action") != "pair":
                    raise ValueError("unknown action")
                return self.send_json({"ok": True, "result": bt_pair(str(b.get("id", "")))})
            elif path == "/api/display" and kind == "local":  # {"action": "try"|"keep"|"undo"|"clear", "mode", "key"}
                a = b.get("action")
                if a == "try":
                    try_mode(b.get("mode") or [])
                elif a == "keep":
                    set_game_mode(str(b.get("key", "")), b.get("mode") or [])
                elif a == "clear":
                    set_game_mode(str(b.get("key", "")))
                elif a == "undo":
                    undo_mode()
                else:
                    raise ValueError("unknown action")
            elif path == "/api/diagnostics" and kind == "local":  # Copy for support: the same text the TV shows
                subprocess.run(["clip.exe"], input="\n".join(diagnostics()).encode("utf-16-le"), timeout=10,
                               creationflags=0x08000000)
                log.info("diagnostics copied to the clipboard")
            elif path == "/api/apps":  # {"action": "add", "kind": "program"|"web", "name", "value"} or {"action": "remove", "id"}
                if b.get("action") == "add":
                    return self.send_json({"ok": True, "id": add_app(str(b.get("kind")), str(b.get("name", "")),
                                                                     str(b.get("value", "")))})
                if b.get("action") == "remove":
                    remove_app(str(b.get("id", "")))
                else:  # order / hide / unhide
                    arrange_apps(str(b.get("action")), str(b.get("id", "")), b.get("ids") or [])
            elif path == "/api/games":
                set_choice(str(b.get("action")), str(b.get("key", "")), str(b.get("value", "")))
            elif path == "/api/settings":  # {"swap": bool}: ✕ and ○ swapped
                with CHOICES_LOCK:
                    c = load_choices()
                    c["swap"] = SWAP[0] = bool(b.get("swap"))
                    save_choices(c)
            elif path == "/api/audio":
                return self.send_json({"ok": True, "name": set_audio(str(b.get("id", "")))})
            elif path == "/api/stream" and kind == "local":  # from stream.cmd: {"on": bool, "device": "Apple TV"}
                return self.send_json({"ok": True, "stream": set_stream(bool(b.get("on")), str(b.get("device", "")))})
            elif path == "/api/sunshine" and kind == "local":  # the Streaming menu, all by controller
                a = b.get("action")
                if a == "open":  # Sunshine's settings page on this screen
                    log.info("opening Sunshine's settings page")
                    subprocess.Popen([CONFIG["edge"], "--new-window", SUNSHINE_URL], creationflags=0x00000008 | 0x00000200)
                    return self.send_json({"ok": True})
                try:
                    if a == "login":
                        ok = sunshine_login(str(b.get("user", "")), str(b.get("password", "")))
                        return self.send_json({"ok": ok} if ok else {"error": "Sunshine didn't accept that username and password."})
                    if a not in SUNSHINE_ACTIONS:
                        return self.send_json({"error": "unknown action"}, 400)
                    log.info("Sunshine: %s", a)
                    return self.send_json({"ok": True, "result": sunshine_api(*SUNSHINE_ACTIONS[a](b))})
                except PermissionError:
                    return self.send_json({"error": "login", "login": False})
                except (OSError, ValueError) as e:  # Sunshine not running, or it restarted mid-call
                    log.info("Sunshine %s failed: %s", a, e)
                    return self.send_json({"error": "Sunshine isn't answering. Try again in a moment."})
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
    display.restore()  # a game's mode left behind by a crash or restart mid-game: back to the desktop's
    if update.check(ROOT.parent):  # at sign-in, before anything starts
        restart_couch()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    WATCHER.start()
    threading.Thread(target=controller_loop, daemon=True).start()
    threading.Thread(target=sleep_watch, daemon=True).start()
    threading.Thread(target=update_watch, daemon=True).start()
    threading.Thread(target=keep_audio, daemon=True).start()
    threading.Thread(target=watch_sunshine, daemon=True).start()
    log.info("listening on port %s; LAN: %s", port, lan_ips())
    print(f"Couch Remote on http://127.0.0.1:{port}  (phone: {', '.join(lan_ips()) or 'no LAN IP'})")
    if want_open:
        threading.Timer(0.5, open_launcher).start()
        threading.Timer(5, warm_rockstar).start()  # after the launcher is up, so there's a Couch to keep in front
    srv.serve_forever()


if __name__ == "__main__":
    if "--child" in sys.argv:
        main()
    else:
        supervise(lambda: subprocess.call([sys.executable, str(Path(__file__).resolve()), "--child", *sys.argv[1:]]))
