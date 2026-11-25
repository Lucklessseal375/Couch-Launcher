"""Windows playback devices: list them and choose the default one (the launcher's Audio output picker).

    python audio.py            list playback devices, * = default
    python audio.py samsung    make the first device whose name contains "samsung" the default

Uses the Windows audio API (MMDevice + the policy interface Windows' own Sound settings use), so no extra installs.
"""
import ctypes
import sys
from ctypes import HRESULT, POINTER, WINFUNCTYPE, byref, c_int, c_uint, c_ulong, c_void_p, c_wchar_p, wintypes

ole32 = ctypes.WinDLL("ole32")
ole32.CoInitializeEx.restype = HRESULT
ole32.CoInitializeEx.argtypes = (c_void_p, wintypes.DWORD)
ole32.CoUninitialize.restype = None
ole32.CoCreateInstance.restype = HRESULT
ole32.CoCreateInstance.argtypes = (c_void_p, c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p))
ole32.CLSIDFromString.restype = HRESULT
ole32.CLSIDFromString.argtypes = (c_wchar_p, c_void_p)
ole32.CoTaskMemFree.restype = None
ole32.CoTaskMemFree.argtypes = (c_void_p,)
ole32.PropVariantClear.restype = HRESULT
ole32.PropVariantClear.argtypes = (c_void_p,)


class GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ole32.CLSIDFromString(text, byref(self))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("val", c_void_p), ("pad", c_void_p)]


CLSID_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
CLSID_POLICY = "{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}"  # PolicyConfigClient: what Sound settings uses
IID_POLICY = "{F8679F50-850A-41CF-9C72-430F290290C8}"    # IPolicyConfig (Windows 7 to 11)
FRIENDLY_NAME = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
CLSCTX_ALL, RENDER, ACTIVE, VT_LPWSTR = 0x17, 0, 1, 31
ROLES = (0, 1, 2)  # console (games, system), multimedia, communications


def _method(obj, index, *argtypes):
    """COM method number `index` of obj (an interface pointer as an int)."""
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtable[index])


def _release(obj):
    if obj:
        WINFUNCTYPE(c_ulong, c_void_p)(ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0][2])(obj)


class _Com:
    """COM for the calling thread (the server calls in from its own threads)."""

    def __enter__(self):
        try:
            ole32.CoInitializeEx(None, 0)  # multithreaded
            self.mine = True
        except OSError:  # already set up differently on this thread: usable as is
            self.mine = False

    def __exit__(self, *exc):
        if self.mine:
            ole32.CoUninitialize()


def _create(clsid, iid):
    obj = c_void_p()
    ole32.CoCreateInstance(byref(GUID(clsid)), None, CLSCTX_ALL, byref(GUID(iid)), byref(obj))
    return obj.value


def _device_id(dev):
    p = c_void_p()
    _method(dev, 5, POINTER(c_void_p))(dev, byref(p))  # IMMDevice::GetId
    try:
        return ctypes.wstring_at(p.value)
    finally:
        ole32.CoTaskMemFree(p)


def _name(dev):
    store = c_void_p()
    _method(dev, 4, wintypes.DWORD, POINTER(c_void_p))(dev, 0, byref(store))  # OpenPropertyStore(read)
    try:
        pv = PROPVARIANT()
        _method(store.value, 5, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(store.value, byref(FRIENDLY_NAME), byref(pv))
        try:
            return ctypes.wstring_at(pv.val) if pv.vt == VT_LPWSTR and pv.val else ""
        finally:
            ole32.PropVariantClear(byref(pv))
    finally:
        _release(store.value)


def _default(enum, role=1):
    dev = c_void_p()
    try:
        _method(enum, 4, c_int, c_int, POINTER(c_void_p))(enum, RENDER, role, byref(dev))  # GetDefaultAudioEndpoint
    except OSError:  # no playback device at all
        return None
    try:
        return _device_id(dev.value)
    finally:
        _release(dev.value)


def default_ids():
    """Ids of the default playback device for each role (games/system, media, calls); None where there's none."""
    with _Com():
        enum = _create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            return tuple(_default(enum, role) for role in ROLES)
        finally:
            _release(enum)


def outputs():
    """Playback devices that are on right now: [{"id", "name", "default"}], in Windows' order."""
    with _Com():
        enum = _create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            default = _default(enum)
            coll = c_void_p()
            _method(enum, 3, c_int, wintypes.DWORD, POINTER(c_void_p))(enum, RENDER, ACTIVE, byref(coll))
            try:
                n = c_uint()
                _method(coll.value, 3, POINTER(c_uint))(coll.value, byref(n))
                found = []
                for i in range(n.value):
                    dev = c_void_p()
                    _method(coll.value, 4, c_uint, POINTER(c_void_p))(coll.value, i, byref(dev))
                    try:
                        did = _device_id(dev.value)
                        found.append({"id": did, "name": _name(dev.value), "default": did == default})
                    finally:
                        _release(dev.value)
                return found
            finally:
                _release(coll.value)
        finally:
            _release(enum)


def set_default(device_id):
    """Make it the default for every role, so games, videos and calls all play there."""
    with _Com():
        policy = _create(CLSID_POLICY, IID_POLICY)
        try:
            set_endpoint = _method(policy, 13, c_wchar_p, c_int)  # IPolicyConfig::SetDefaultEndpoint
            for role in ROLES:
                set_endpoint(policy, device_id, role)
        finally:
            _release(policy)


if __name__ == "__main__":
    devices = outputs()
    if len(sys.argv) > 1:
        match = next((d for d in devices if sys.argv[1].lower() in d["name"].lower()), None)
        if not match:
            sys.exit(f"no playback device matching {sys.argv[1]!r}")
        set_default(match["id"])
        print("default is now", match["name"])
        devices = outputs()
    for d in devices:
        print("*" if d["default"] else " ", d["name"])


# ---------------------------------------------------------------- volume and microphone (IAudioEndpointVolume)
IID_ENDPOINT_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"
CAPTURE = 1


def _with_volume(flow, role, fn):
    """fn(volume interface) on the default device for flow (RENDER or CAPTURE) and role; None if there's no device."""
    with _Com():
        enum = _create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            dev = c_void_p()
            try:
                _method(enum, 4, c_int, c_int, POINTER(c_void_p))(enum, flow, role, byref(dev))
            except OSError:
                return None
            try:
                vol = c_void_p()
                _method(dev.value, 3, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(  # IMMDevice::Activate
                    dev.value, byref(GUID(IID_ENDPOINT_VOLUME)), CLSCTX_ALL, None, byref(vol))
                try:
                    return fn(vol.value)
                finally:
                    _release(vol.value)
            finally:
                _release(dev.value)
        finally:
            _release(enum)


def _level(v):
    f = ctypes.c_float()
    _method(v, 9, POINTER(ctypes.c_float))(v, byref(f))  # GetMasterVolumeLevelScalar
    return f.value


def _muted(v):
    b = wintypes.BOOL()
    _method(v, 15, POINTER(wintypes.BOOL))(v, byref(b))  # GetMute
    return bool(b.value)


def volume_state():
    """{"level": 0-100, "muted", "mic": True/False/None (no microphone)} for the default devices."""
    out = _with_volume(RENDER, 0, lambda v: {"level": round(_level(v) * 100), "muted": _muted(v)}) or {"level": None, "muted": False}
    out["micMuted"] = _with_volume(CAPTURE, 0, _muted)
    return out


def set_volume(level=None, muted=None):
    def apply(v):
        if level is not None:
            _method(v, 7, ctypes.c_float, c_void_p)(v, max(0, min(100, level)) / 100, None)  # SetMasterVolumeLevelScalar
        if muted is not None:
            _method(v, 14, wintypes.BOOL, c_void_p)(v, bool(muted), None)  # SetMute
    _with_volume(RENDER, 0, apply)


def set_mic_muted(muted):
    """Mutes or unmutes the default microphone, for games and for calls (Discord uses the communications one)."""
    for role in (0, 2):
        _with_volume(CAPTURE, role, lambda v: _method(v, 14, wintypes.BOOL, c_void_p)(v, bool(muted), None))


# ---------------------------------------------------------------- per-app volume (audio sessions, like Windows' Volume mixer)
IID_SESSION_MANAGER2 = "{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"
IID_SESSION_CONTROL2 = "{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}"
IID_SIMPLE_VOLUME = "{87CE5498-68D6-44E5-9215-6DA47EF883D8}"
kernel32 = ctypes.WinDLL("kernel32")


def _query(obj, iid):
    out = c_void_p()
    _method(obj, 0, POINTER(GUID), POINTER(c_void_p))(obj, byref(GUID(iid)), byref(out))  # QueryInterface
    return out.value


def _exe_of(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        return buf.value.rsplit("\\", 1)[-1].lower() if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def _sessions(fn):
    """fn(exe name, pid, ISimpleAudioVolume) for each app's sound session on the default output (not Windows' own
    sounds, not ones that have ended)."""
    def each(mgr):
        enum = c_void_p()
        _method(mgr, 5, POINTER(c_void_p))(mgr, byref(enum))  # GetSessionEnumerator
        try:
            n = c_int()
            _method(enum.value, 3, POINTER(c_int))(enum.value, byref(n))
            for i in range(n.value):
                ctl = c_void_p()
                _method(enum.value, 4, c_int, POINTER(c_void_p))(enum.value, i, byref(ctl))
                try:
                    state = c_int()
                    _method(ctl.value, 3, POINTER(c_int))(ctl.value, byref(state))
                    ctl2 = _query(ctl.value, IID_SESSION_CONTROL2)
                    try:
                        if state.value == 2 or _method(ctl2, 15)(ctl2) == 0:  # expired, or the system sounds session
                            continue
                        pid = wintypes.DWORD()
                        _method(ctl2, 14, POINTER(wintypes.DWORD))(ctl2, byref(pid))
                        exe = _exe_of(pid.value)
                        if exe:
                            vol = _query(ctl.value, IID_SIMPLE_VOLUME)
                            try:
                                fn(exe, pid.value, vol)
                            finally:
                                _release(vol)
                    finally:
                        _release(ctl2)
                finally:
                    _release(ctl.value)
        finally:
            _release(enum.value)

    with _Com():
        enum = _create(CLSID_ENUMERATOR, IID_ENUMERATOR)
        try:
            dev = c_void_p()
            try:
                _method(enum, 4, c_int, c_int, POINTER(c_void_p))(enum, RENDER, 0, byref(dev))
            except OSError:
                return
            try:
                mgr = c_void_p()
                _method(dev.value, 3, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(
                    dev.value, byref(GUID(IID_SESSION_MANAGER2)), CLSCTX_ALL, None, byref(mgr))
                try:
                    each(mgr.value)
                finally:
                    _release(mgr.value)
            finally:
                _release(dev.value)
        finally:
            _release(enum)


def app_sessions():
    """[{"exe", "pid", "level": 0-100, "muted"}], one per program process with sound on the default output."""
    found = {}

    def read(exe, pid, v):
        f, m = ctypes.c_float(), wintypes.BOOL()
        _method(v, 4, POINTER(ctypes.c_float))(v, byref(f))  # GetMasterVolume
        _method(v, 6, POINTER(wintypes.BOOL))(v, byref(m))   # GetMute
        found.setdefault(pid, {"exe": exe, "pid": pid, "level": round(f.value * 100), "muted": bool(m.value)})
    _sessions(read)
    return list(found.values())


def set_session_volume(pids, level):
    """Every sound session of those processes to level (0-100), and unmuted when turned up."""
    def write(_exe, pid, v):
        if pid in pids:
            _method(v, 3, ctypes.c_float, c_void_p)(v, max(0, min(100, level)) / 100, None)  # SetMasterVolume
            if level > 0:
                _method(v, 5, wintypes.BOOL, c_void_p)(v, False, None)  # SetMute(false)
    _sessions(write)
