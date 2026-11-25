"""The TV's display mode (resolution and refresh rate), for per-game modes. Changes are dynamic (not saved in Windows'
settings), so restore() or a reboot always gets back to the desktop's own mode. HDR is left alone: Windows barely
documents switching it.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
ENUM_CURRENT_SETTINGS = -1
DM_BITSPERPEL, DM_PELSWIDTH, DM_PELSHEIGHT, DM_DISPLAYFREQUENCY = 0x40000, 0x80000, 0x100000, 0x400000
CDS_TEST = 0x2
DISP_CHANGE_SUCCESSFUL = 0


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


def _devmode():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


def current():
    """(width, height, hz) the main display shows now."""
    dm = _devmode()
    user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    return dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency


def modes():
    """Every (width, height, hz) the main display offers in full colour, biggest first."""
    found, i, dm = set(), 0, _devmode()
    while user32.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
        if dm.dmBitsPerPel >= 32 and dm.dmDisplayFrequency > 1:
            found.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        i += 1
    return sorted(found, reverse=True)


def choices(all_modes, now):
    """A short list for the TV, at most 7: the main sizes (4K, 1440p, 1080p, 720p) at their highest refresh, and the
    faster refresh rates of the current size. `now` comes first."""
    best = {}
    for w, h, hz in all_modes:
        if (w, h) in ((3840, 2160), (2560, 1440), (1920, 1080), (1280, 720)) and hz > best.get((w, h), 0):
            best[(w, h)] = hz
    picks = [now] + [(w, h, hz) for (w, h), hz in best.items()] + [m for m in all_modes if m[:2] == now[:2] and m[2] > now[2]]
    out = []
    for m in picks:
        if m not in out:
            out.append(m)
    return out[:7]


def apply(w, h, hz):
    """Switches to the mode for now (not saved: restore() or a reboot undoes it). True if Windows took it."""
    dm = _devmode()
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel = w, h, hz, 32
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY | DM_BITSPERPEL
    if user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_TEST, None) != DISP_CHANGE_SUCCESSFUL:
        return False
    return user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, 0, None) == DISP_CHANGE_SUCCESSFUL


def restore():
    """Back to the mode saved in Windows' display settings (the desktop's own)."""
    return user32.ChangeDisplaySettingsExW(None, None, None, 0, None) == DISP_CHANGE_SUCCESSFUL


def label(w, h, hz):
    names = {(3840, 2160): "4K", (2560, 1440): "1440p", (1920, 1080): "1080p", (1280, 720): "720p"}
    return f"{names.get((w, h), f'{w}×{h}')} at {hz} Hz"
