"""App tiles you add from the launcher (its "Add app" tile). Programs come only from Windows' own Start menu list, so
nothing is typed and no path or command can be slipped in; websites must be https. They're kept in choices.json
("added"), not apps.json, because updates replace apps.json.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

WINDOWS = os.environ.get("SystemRoot", r"C:\Windows")
KNOWN_FOLDERS = {  # how the Start menu writes these folders in an app id
    "{6D809377-6AF0-444B-8957-A3773F02200E}": os.environ.get("ProgramW6432", r"C:\Program Files"),
    "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": str(Path(WINDOWS) / "System32"),
    "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": WINDOWS,
}
_CACHE = [0.0, []]


def keep(name, app_id):
    """Start menu entries worth a tile: not uninstallers, documents or web links."""
    return bool(name and app_id) and not re.match(r"(?i)https?:", app_id) and not re.match(r"(?i)uninstall", name) \
        and not re.search(r"(?i)\.(txt|url|chm|html?|pdf|rtf|lnk)$", app_id)


def start_apps():
    """[(name, app id)] from the Start menu, sorted by name. Cached a minute (PowerShell takes a second or two)."""
    if time.time() - _CACHE[0] > 60:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", timeout=60, creationflags=0x08000000)
        items = json.loads(r.stdout or "[]")
        items = [items] if isinstance(items, dict) else items
        found = {(i.get("Name"), i.get("AppID")) for i in items if keep(i.get("Name"), i.get("AppID"))}
        _CACHE[:] = [time.time(), sorted(found, key=lambda x: x[0].lower())]
    return _CACHE[1]


def tile_for(name, app_id):
    """The tile for a Start menu entry: its program when the id is a path (so Couch shows its icon and knows its
    window), else opened the way the Start menu opens it (shell:AppsFolder, e.g. Store apps)."""
    path = app_id
    for guid, folder in KNOWN_FOLDERS.items():
        if path.upper().startswith(guid):
            path = folder + path[len(guid):]
    if path.lower().endswith(".exe") and Path(path).is_file():
        return {"name": name, "kind": "exe", "target": path}
    return {"name": name, "kind": "exe", "target": str(Path(WINDOWS) / "explorer.exe"),
            "args": ["shell:AppsFolder\\" + app_id]}


def clean_name(name):
    return re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:40]


def make_tile(kind, name, value, programs):
    """Checks what the launcher sent and returns the new tile (no id yet). Raises ValueError with a message for the TV."""
    name = clean_name(name)
    if kind == "program":
        hit = next(((n, i) for n, i in programs if i == value), None)
        if not hit:
            raise ValueError("Pick a program from the Start menu list")
        tile = tile_for(name or hit[0], value)
    elif kind == "web":
        value = value.strip()
        u = urlparse(value)
        if u.scheme != "https" or not u.hostname or len(value) > 500 or any(c.isspace() for c in value):
            raise ValueError("Use a website address that starts with https://")
        tile = {"name": name or u.hostname.removeprefix("www."), "kind": "web", "target": value}
    else:
        raise ValueError("Unknown kind of app")
    tile["meta"] = "Added by you"
    tile["color"] = "#3a2716"  # the race's dusk, behind a tile whose icon can't be found
    return tile


def new_id(name, taken):
    base = "my-" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app")
    return next(i for i in (base if n == 0 else f"{base}-{n}" for n in range(1000)) if i not in taken)
