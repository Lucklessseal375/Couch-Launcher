"""Full-size screenshots of the launcher/remote through headless Edge's DevTools port (dev helper, not part of the app).

    python dev/shoot.py dev/shots-example.json <out_dir>

While it runs, the headless page is the newest launcher page, so controller presses go to it (seconds).

steps.json: {"url": ..., "width": 1920, "height": 1080, "steps": [{"js": "...", "wait": 800, "shot": "name.png"}, ...]}
Each step runs its JS (awaited), waits, finishes non-infinite animations, then saves a PNG if "shot" is set.
Never put anything in "js" that launches, sleeps or restarts: the page talks to the real server.
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333


class WS:
    """Just enough of a websocket client for DevTools (text frames, client masking, fragmented replies)."""

    def __init__(self, url):
        host, rest = url[len("ws://"):].split("/", 1)
        h, p = host.split(":")
        self.s = socket.create_connection((h, int(p)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += self.s.recv(1)
        assert b" 101 " in resp.split(b"\r\n")[0], resp
        self.n = 0

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def send(self, method, **params):
        self.n += 1
        data = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        hdr = bytes([0x81])
        if len(data) < 126:
            hdr += bytes([0x80 | len(data)])
        elif len(data) < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", len(data))
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:  # skip events until our reply arrives
            msg = json.loads(self.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def recv(self):
        out = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            out += self._read(n)
            if b1 & 0x80:
                return out.decode()


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    w, h = spec.get("width", 1920), spec.get("height", 1080)
    prof = tempfile.mkdtemp(prefix="shoot-")
    edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             f"--window-size={w},{h}", "--force-device-scale-factor=1", "--hide-scrollbars",
                             "--mute-audio", "--no-first-run", "about:blank"])
    try:
        for _ in range(50):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
                page = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        ws = WS(page["webSocketDebuggerUrl"])
        ws.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=bool(spec.get("mobile")))
        ws.send("Page.enable")
        ws.send("Page.navigate", url=spec["url"])
        time.sleep(spec.get("load_wait", 3))
        for st in spec["steps"]:
            if st.get("js"):
                r = ws.send("Runtime.evaluate", expression=f"(async () => {{ {st['js']} }})()", awaitPromise=True,
                            returnByValue=True)
                if r.get("exceptionDetails"):
                    print("JS error:", r["exceptionDetails"].get("exception", {}).get("description"))
                elif r.get("result", {}).get("value") is not None:
                    print("->", r["result"]["value"])
            time.sleep(st.get("wait", 600) / 1000)
            ws.send("Runtime.evaluate", expression="document.getAnimations().forEach(a => { if (a.effect?.getTiming().iterations !== Infinity) try { a.finish() } catch {} })")
            if st.get("shot"):
                png = base64.b64decode(ws.send("Page.captureScreenshot", format="png")["data"])
                path = os.path.join(out_dir, st["shot"])
                open(path, "wb").write(png)
                print("saved", path)
        try:
            ws.send("Browser.close")
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            edge.wait(5)
        except subprocess.TimeoutExpired:
            edge.kill()


if __name__ == "__main__":
    main()
