"""Pair Bluetooth devices from the TV (PC row → Bluetooth), through Windows' own pairing (WinRT, via the pywinrt
packages the installer adds). Couch only finds and pairs; forgetting a device stays in Windows' settings.
"""
import asyncio
import time

try:
    from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation, DevicePairingKinds, DevicePairingResultStatus
except ImportError:  # the packages aren't installed (run Install Couch.cmd once): the tile says so
    DeviceInformation = None


def available():
    return DeviceInformation is not None


def paired():
    """Names of the devices Windows has paired (classic Bluetooth: controllers, headphones, speakers)."""
    async def go():
        found = await DeviceInformation.find_all_async_aqs_filter(BluetoothDevice.get_device_selector_from_pairing_state(True))
        return sorted({d.name for d in found if d.name})
    return asyncio.run(go())


def scan(seconds=12):
    """[{"id", "name"}] of devices nearby that are ready to pair, found for `seconds` (classic and Bluetooth LE).
    Unnamed devices are left out: nobody could tell which is which on the TV."""
    found = {}

    def watcher(selector, classic):
        def added(_w, info):  # classic: controllers, headphones, speakers; LE (washers, lights) only when pairable
            if info.name and not info.pairing.is_paired and (classic or info.pairing.can_pair):
                found.setdefault(info.name, info.id)
        w = DeviceInformation.create_watcher_aqs_filter(selector)
        w.add_added(added)
        w.add_updated(lambda _w, _u: None)  # without an Updated handler Windows never reports anything
        w.start()
        return w

    watchers = [watcher(BluetoothDevice.get_device_selector_from_pairing_state(False), True),
                watcher(BluetoothLEDevice.get_device_selector_from_pairing_state(False), False)]
    time.sleep(seconds)
    for w in watchers:
        try:
            w.stop()
        except OSError:
            pass
    return [{"id": i, "name": n} for n, i in sorted(found.items(), key=lambda x: x[0].lower())]


def pair(device_id):
    """Pairs one device found by scan(). Returns a short result for the TV. Devices that show a code or ask to confirm
    one are accepted as Windows' own quick pairing does; ones that need a typed PIN aren't supported here."""
    async def go():
        info = await DeviceInformation.create_from_id_async(device_id)
        custom = info.pairing.custom
        token = custom.add_pairing_requested(lambda _s, args: args.accept())
        try:
            kinds = DevicePairingKinds.CONFIRM_ONLY | DevicePairingKinds.DISPLAY_PIN | DevicePairingKinds.CONFIRM_PIN_MATCH
            result = await custom.pair_async(kinds)
        finally:
            custom.remove_pairing_requested(token)
        return result.status
    status = asyncio.run(go())
    if status in (DevicePairingResultStatus.PAIRED, DevicePairingResultStatus.ALREADY_PAIRED):
        return "paired"
    return {DevicePairingResultStatus.AUTHENTICATION_TIMEOUT: "it didn't answer in time",
            DevicePairingResultStatus.CONNECTION_REJECTED: "it said no",
            DevicePairingResultStatus.PAIRING_CANCELED: "pairing was cancelled",
            DevicePairingResultStatus.NO_SUPPORTED_PAIRING_KINDS: "it needs a PIN typed in Windows' Bluetooth settings",
            }.get(status, "it couldn't pair (make sure it's still in pairing mode)")
