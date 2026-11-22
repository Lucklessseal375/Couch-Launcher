"""Launcher sounds on a DualSense's own speaker, and felt in its grips, over Bluetooth.

Windows offers the controller's speaker as a sound device only over USB. Over Bluetooth a PS5 sends it Opus audio
and haptic samples inside HID output report 0x39, so this does the same: the launcher page posts what it plays
(see feed) and a thread paces it out to every DualSense connected over Bluetooth, then lets the link rest.
Report layout and rates follow dualsense_BT_audio (src/ds5.h), which documents KytyPS5 and DS5Dongle (MIT).
"""
import ctypes
import importlib.util
import logging
import threading
import time
import zlib
from array import array
from ctypes import wintypes
from pathlib import Path

RATE = 45000          # the controller plays its "48 kHz" Opus stream at 45 kHz
BLOCK = 960           # samples per report: two 480-sample Opus frames, 21.333 ms
PERIOD = BLOCK / RATE
FRAME = 200           # bytes per Opus frame: CBR 160 kbit/s
FEEL = 128            # haptic bytes per report: 64 frames x 2 grips, signed 8-bit at 3 kHz
BLOCK_BYTES = BLOCK * 2 + FEEL  # one posted block: 960 16-bit mono samples at 45 kHz, then the grips' samples
MAX_BLOCKS = 10       # buffered sound cap (~210 ms), so the delay stays short if the page runs ahead
VOLUME = 100          # the controller's speaker volume: 100 is its top (the launcher's own sliders set the levels)
PREAMP = 7            # its speaker preamp, 0..7: 2 = +6 dB (what Linux uses), 7 = as loud as it goes

log = logging.getLogger("couch")


# ---------- the reports
def _sealed(r):
    """Bluetooth output reports end in a CRC-32 of a 0xA2 HIDP header plus the report."""
    r[-4:] = zlib.crc32(b"\xa2" + r[:-4]).to_bytes(4, "little")
    return bytes(r)


def control_report(volume=VOLUME, preamp=PREAMP):
    """0x31: sound to the speaker (headphone jack muted), the speaker volume and its preamp gain, and the grips at
    full strength: no motor power reduction, no built-in haptic low-pass (their bytes, r[39] and r[42], stay 0)."""
    r = bytearray(78)
    r[0:3] = b"\x31\x00\x10"
    r[3] = 0xA0                        # valid: audio control + speaker volume
    r[4] = 0x80 | 0x40 | 0x20          # valid: audio control 2, motor power level, haptic low-pass filter
    r[8], r[10], r[40] = volume, 0x30, preamp & 7
    return _sealed(r)


def audio_report(i, opus, feel=bytes(FEEL)):
    """0x39 number i: one 21.333 ms block: haptic samples for the grips, then two Opus frames for the speaker."""
    r = bytearray(547)
    r[0:12] = bytes((0x39, (i & 15) << 4, 0x91, 6, 0x7E, 48, 48, 48, 48, i * 2 & 255, 0xD2, 64))
    r[12:12 + FEEL] = feel
    r[140:142] = bytes((0xD3, FRAME))
    r[142:142 + 2 * FRAME] = opus
    return _sealed(r)


# ---------- the controllers
class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


HID_INTERFACE = _GUID(0x4D1E55B2, 0xF16F, 0x11CF, (ctypes.c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30))
cfgmgr = ctypes.WinDLL("cfgmgr32")
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                            wintypes.DWORD, wintypes.HANDLE)
k32.WriteFile.argtypes = (wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                          wintypes.LPVOID)
k32.CloseHandle.argtypes = (wintypes.HANDLE,)
hid = ctypes.WinDLL("hid")
hid.HidD_SetOutputReport.argtypes = (wintypes.HANDLE, ctypes.c_char_p, wintypes.ULONG)
INVALID_HANDLE = wintypes.HANDLE(-1).value


def is_bt_dualsense(path):
    p = path.lower()  # {00001124-...} is the Bluetooth HID service; 0ce6 = DualSense, 0df2 = DualSense Edge
    return "{00001124-" in p and "vid&0002054c" in p and ("pid&0ce6" in p or "pid&0df2" in p)


def pad_paths():
    """HID paths of the DualSenses connected over Bluetooth right now."""
    n = wintypes.ULONG()
    if cfgmgr.CM_Get_Device_Interface_List_SizeW(ctypes.byref(n), ctypes.byref(HID_INTERFACE), None, 0):
        return []
    buf = ctypes.create_unicode_buffer(n.value)
    if cfgmgr.CM_Get_Device_Interface_ListW(ctypes.byref(HID_INTERFACE), None, buf, n, 0):
        return []  # a device came or went in between; the next call sees it
    return [p for p in buf[:n.value].split("\0") if is_bt_dualsense(p)]


hid.HidD_GetSerialNumberString.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG)
k32.DeviceIoControl.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
bth = ctypes.WinDLL("bthprops.cpl")
bth.BluetoothFindFirstRadio.restype = wintypes.HANDLE
bth.BluetoothFindFirstRadio.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE))
bth.BluetoothFindNextRadio.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE))
bth.BluetoothFindRadioClose.argtypes = (wintypes.HANDLE,)
IOCTL_BTH_DISCONNECT_DEVICE = 0x41000C


def addresses():
    """Bluetooth addresses of the connected DualSenses (Windows gives a Bluetooth HID device's MAC as its serial)."""
    out = []
    for p in pad_paths():
        h = k32.CreateFileW(p, 0, 3, None, 3, 0, None)  # no read/write access needed just to ask
        if h in (None, INVALID_HANDLE):
            continue
        buf = ctypes.create_unicode_buffer(32)
        if hid.HidD_GetSerialNumberString(h, buf, ctypes.sizeof(buf)):
            try:
                out.append(int(buf.value, 16))  # "0c27566ea39d" -> 0x0C27566EA39D
            except ValueError:
                pass
        k32.CloseHandle(h)
    return out


def turn_off():
    """Drops the Bluetooth link to every wireless DualSense, so it powers off as on a PS5; it stays paired and
    the PS button connects it again. Returns how many went off."""
    addrs = addresses()
    radios, radio = [], wintypes.HANDLE()
    size = wintypes.DWORD(4)  # BLUETOOTH_FIND_RADIO_PARAMS is just its own size
    find = bth.BluetoothFindFirstRadio(ctypes.byref(size), ctypes.byref(radio)) if addrs else None
    if find:
        radios.append(radio.value)
        while bth.BluetoothFindNextRadio(find, ctypes.byref(radio)):
            radios.append(radio.value)
        bth.BluetoothFindRadioClose(find)
    n = 0
    for a in addrs:
        for r in radios:
            if k32.DeviceIoControl(r, IOCTL_BTH_DISCONNECT_DEVICE, ctypes.byref(ctypes.c_ulonglong(a)), 8,
                                   None, 0, ctypes.byref(wintypes.DWORD()), None):
                n += 1
                break
    for r in radios:
        k32.CloseHandle(r)
    return n


def write(h, report):
    n = wintypes.DWORD()
    # Some Bluetooth stacks refuse big interrupt writes; the controller takes the report as a control transfer too.
    return bool(k32.WriteFile(h, report, len(report), ctypes.byref(n), None)
                or hid.HidD_SetOutputReport(h, report, len(report)))


def keep(pads, report):
    """The pads that took the report; the rest (turned off, out of range) are closed."""
    ok = []
    for h in pads:
        if write(h, report):
            ok.append(h)
        else:
            k32.CloseHandle(h)
    return ok


# ---------- Opus, from the libopus that pygame ships (for SDL_mixer)
def _load_opus():
    try:
        lib = ctypes.CDLL(str(Path(importlib.util.find_spec("pygame").submodule_search_locations[0]) / "libopus-0.dll"))
    except (AttributeError, TypeError, OSError):
        return None
    lib.opus_encoder_create.restype = ctypes.c_void_p
    lib.opus_encode.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int32)
    return lib


class Encoder:
    def __init__(self, lib):
        err = ctypes.c_int()
        self.lib, self.st = lib, ctypes.c_void_p(lib.opus_encoder_create(48000, 2, 2049, ctypes.byref(err)))  # AUDIO
        if err.value or not self.st.value:
            raise OSError(f"opus_encoder_create failed: {err.value}")
        for request, value in ((4002, 160000), (4006, 0), (4010, 0)):  # bitrate, hard CBR, complexity 0
            lib.opus_encoder_ctl(self.st, request, ctypes.c_int(value))
        self.out = ctypes.create_string_buffer(FRAME)

    def encode(self, stereo):
        """Two Opus frames (400 bytes) for one block of interleaved 16-bit stereo samples (an array("h"))."""
        frames = b""
        for k in range(2):
            n = self.lib.opus_encode(self.st, stereo.buffer_info()[0] + k * 480 * 4, 480, self.out, FRAME)
            frames += self.out.raw if n == FRAME else bytes(FRAME)  # a frame that fails plays as silence
        return frames


# ---------- the stream
class Speaker:
    def __init__(self):
        self.opus = _load_opus()
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.streaming = False
        self.dead_until = 0.0  # a controller is listed but won't take reports: stop offering it for a while
        if self.opus:
            threading.Thread(target=self._run, name="pad-speaker", daemon=True).start()

    def available(self):
        return bool(self.opus) and time.monotonic() > self.dead_until and bool(pad_paths())

    def feed(self, blocks):
        """Queue whole blocks (BLOCK_BYTES each). False: there's no wireless controller to play them on."""
        if not (self.streaming or self.available()):
            return False
        with self.lock:
            self.buf += blocks
            del self.buf[:max(0, len(self.buf) - MAX_BLOCKS * BLOCK_BYTES)]
        self.wake.set()
        return True

    def _run(self):
        enc, stereo = Encoder(self.opus), array("h", bytes(BLOCK * 4))
        while True:
            self.wake.wait()
            self.wake.clear()
            paths = pad_paths()
            pads = keep([h for h in (k32.CreateFileW(p, 0xC0000000, 3, None, 3, 0, None) for p in paths)
                         if h and h != INVALID_HANDLE], control_report())  # shared: SDL and Steam keep it open too
            if not pads:
                if paths:
                    log.warning("the controller won't take speaker reports (error %s)", ctypes.get_last_error())
                    self.dead_until = time.monotonic() + 30
                with self.lock:
                    self.buf.clear()
                continue
            self.streaming = True
            ready = time.monotonic() + 0.1
            while len(self.buf) < 3 * BLOCK_BYTES and time.monotonic() < ready:  # a head start absorbs posting jitter
                time.sleep(0.005)
            start, i, quiet = time.perf_counter() - 2 * PERIOD, 0, 0  # the first three go at once to fill its buffer
            while pads and quiet < 50:  # about a second with nothing new: let the link rest
                with self.lock:
                    chunk = bytes(self.buf[:BLOCK_BYTES])
                    del self.buf[:BLOCK_BYTES]
                quiet = 0 if chunk else quiet + 1
                chunk = chunk or bytes(BLOCK_BYTES)
                mono = array("h", chunk[:BLOCK * 2])
                stereo[0::2] = mono
                stereo[1::2] = mono
                pads = keep(pads, audio_report(i, enc.encode(stereo), chunk[BLOCK * 2:]))
                i += 1
                wait = start + i * PERIOD - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                elif wait < -3 * PERIOD:  # a long stall (the PC was busy): carry on from now instead of bursting
                    start -= wait
            for h in pads:
                k32.CloseHandle(h)
            self.streaming = False


if __name__ == "__main__":  # python padspeaker.py: a two-note chime on every wireless DualSense, with a tap you feel
    import math
    s = Speaker()
    print("wireless DualSenses:", pad_paths() or "none", "| opus:", bool(s.opus))
    for n in range(46):  # about a second: two notes, each starting with a short 150 Hz thump in the grips
        f, age = (660, n) if n < 23 else (990, n - 23)
        sound = array("h", (int(9000 * (1 - age / 23) * math.sin(2 * math.pi * f * (n * BLOCK + k) / RATE)) for k in range(BLOCK)))
        thump = array("b", (int(110 * max(0.0, 1 - age / 4) * math.sin(2 * math.pi * 150 * (n * 64 + k // 2) / 3000))
                            for k in range(FEEL)))
        s.feed(sound.tobytes() + thump.tobytes())
        time.sleep(PERIOD)
    time.sleep(1.5)
