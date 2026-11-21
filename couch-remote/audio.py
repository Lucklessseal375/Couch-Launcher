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
