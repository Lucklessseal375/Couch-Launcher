# Couch over Sunshine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Moonlight on the Apple TV opens "Couch" through Sunshine, Couch knows a stream is on, says so in its header, and leaves the audio alone; with no stream nothing changes.

**Architecture:** Sunshine's per-app *prep commands* (run on stream start and end) call a tiny `stream.cmd` that POSTs to a new local-only `/api/stream` endpoint. The server keeps `STREAM` state, pushes `stream:<device>` / `stream:off` to the page (same channel as `pad:`), includes it in `/api/info`, and `audio_replaced` returns None while streaming. The page shows a header pill.

**Tech Stack:** Python stdlib server (`couch-remote/server.py`), unittest, plain JS/CSS in `web/launcher.html`, a Windows `.cmd` using the built-in `curl.exe`.

**Spec:** `docs/superpowers/specs/2026-11-22-sunshine-streaming-design.md`

**Builder's call recorded here (spec left the signal open):** use Sunshine's app prep commands instead of parsing Sunshine's log. Reason: works and can be tested before Sunshine is installed, no log format to guess, stays read-only toward Sunshine's settings. The device name comes from the command (`stream.cmd on "Apple TV"`), default "another screen".

## Global Constraints

- Python stdlib only; no new dependencies.
- Couch never installs software, never writes Sunshine's settings, never stores a Sunshine password.
- Home network only; `/api/stream` accepts local requests only (`kind == "local"`), like `/api/light`.
- No behaviour change without a stream: all existing tests keep passing.
- Tests never reach real launchers, `choices.json`, or `server.log` (`server.log.disabled = True`, mocks in `setUp`).

## Review Focus

- `stream.cmd off` arriving without an earlier `on` (Sunshine restarted mid-stream, or the user ran it): state ends "off", no error.
- `on` twice (two Moonlight sessions or a reconnect): stays on, device updated, one pill.
- Device names with quotes or `<`: shown as text, never as HTML.
- Couch server restarted during a stream: state is lost (off) until the next `on`; accepted, documented in setup notes.
- A stream ends while the living-room TV is asleep: `keep_audio` resumes and its existing "chosen output is off" rule still applies.

---

### Task 1: Stream state and `/api/stream` in the server

**Files:**
- Modify: `couch-remote/server.py` (near `audio_replaced` ~l.287; POST handler near `/api/light` ~l.1859; `/api/info` ~l.1765)
- Test: `couch-remote/tests/test_stream.py` (create)

**Interfaces:**
- Produces: `STREAM: dict` = `{"on": bool, "device": str}`; `set_stream(on: bool, device: str = "") -> dict` (updates `STREAM`, logs, emits `"stream:" + device` or `"stream:off"`, returns a copy); `/api/info` gains `"stream": device or None`; `POST /api/stream {"on": bool, "device": str}` (local only) returns `{"ok": true, "stream": {...}}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_stream.py` (same header as `tests/test_weather.py`, `server.log.disabled = True`; reset `STREAM` to off in `setUp`/cleanup; patch `server.emit`):
  - `test_on_then_off_emits_and_updates`: `set_stream(True, "Apple TV")` → `STREAM == {"on": True, "device": "Apple TV"}`, emit called with `"stream:Apple TV"`; `set_stream(False)` → `STREAM["on"] is False`, emit `"stream:off"`.
  - `test_on_without_device_names_another_screen`: `set_stream(True, "")` → device `"another screen"`.
  - `test_off_without_on_is_fine`: `set_stream(False)` from off → no exception, emit `"stream:off"`.
  - `test_device_name_trimmed_to_40_chars`: 60-char name → `len(STREAM["device"]) == 40`.
  - `test_audio_left_alone_while_streaming`: with `STREAM["on"] = True`, `audio_replaced({"id": "tv", "name": "TV"}, ["other"], {"tv": "TV", "other": "Speakers"})` is `None`; with it off, the same call returns `{"Speakers"}`.

- [ ] **Step 2: Run** `python -m unittest tests.test_stream -v` from `couch-remote`. Expected: FAIL (`set_stream` not defined).

- [ ] **Step 3: Implement** `STREAM` and `set_stream` above `audio_replaced`; make `audio_replaced` return `None` first thing when `STREAM["on"]`; add the local-only `elif path == "/api/stream" and kind == "local":` branch (reads `b.get("on")` as bool, `str(b.get("device", ""))`); add `"stream": STREAM["device"] if STREAM["on"] else None` to the `/api/info` dict.

- [ ] **Step 4: Run** `python -m unittest discover -s tests` from `couch-remote`. Expected: all pass (37 old + 5 new).

- [ ] **Step 5: Commit** `server.py`, `tests/test_stream.py`: "Stream state from Sunshine prep commands: /api/stream, audio stands down".

### Task 2: `stream.cmd` and the one-time setup notes

**Files:**
- Create: `couch-remote/stream.cmd`
- Create: `docs/streaming-setup.md`

**Interfaces:**
- Consumes: `POST /api/stream`, `POST /api/window {"action":"launcher"}` (both need header `X-Couch: 1`).
- Produces: `stream.cmd on ["Device name"]` → stream on + open/focus the launcher; `stream.cmd off` → stream off. Exit code 0 even if Couch isn't running (Sunshine must not abort the stream).

- [ ] **Step 1: Write `stream.cmd`** using `%SystemRoot%\System32\curl.exe -s -m 5 -X POST -H "X-Couch: 1" -H "Content-Type: application/json"` to `http://127.0.0.1:8765`; JSON built with escaped quotes; `exit /b 0` at the end.

- [ ] **Step 2: Verify by hand** (server running, no Sunshine needed): `couch-remote\stream.cmd on "Apple TV"` → `curl -s -H X-Couch:1 http://127.0.0.1:8765/api/info` shows `"stream": "Apple TV"` and server.log has `stream: on (Apple TV)`; `stream.cmd off` → `"stream": null`. With the server stopped, `stream.cmd on` exits 0.

- [ ] **Step 3: Write `docs/streaming-setup.md`**: install Sunshine from its official GitHub releases (user does it); in Sunshine's web page (Applications) add app **Couch** with *Command* left empty and *Prep commands* Do = `"<repo>\couch-remote\stream.cmd" on "Apple TV"`, Undo = `"<repo>\couch-remote\stream.cmd" off`; start at 1080p60 on Wi-Fi; install Moonlight on the Apple TV, pair with Sunshine's PIN, pair the PS5 controller to the Apple TV; known limit: restarting Couch mid-stream drops the "streaming" state until the next connect.

- [ ] **Step 4: Commit** `stream.cmd`, `docs/streaming-setup.md`: "stream.cmd for Sunshine prep commands, and setup steps".

### Task 3: "Streaming to …" pill in the launcher header

**Files:**
- Modify: `couch-remote/web/launcher.html` (header markup `.status` ~l.346; CSS next to `#bell`; `onPad` ~"if (a.startsWith(\"pad:\"))"; build/refresh where `info` arrives)

**Interfaces:**
- Consumes: `info.stream` (string or null), pushed `stream:<device>` / `stream:off`.
- Produces: `showStream(device: string | null)` setting `#stream` (hidden when null) with `textContent` "Streaming to " + device.

- [ ] **Step 1: Add** `<div id="stream" hidden></div>` before `#weather`, CSS like `#bell` (pill: `--bib` background, white text, `1vh` radius; `[hidden]` → none); `showStream` using `textContent` (never innerHTML); call it from where `info` is applied and from `onPad` for `stream:` messages (`"off"` → null), returning before the input-handling part of `onPad` like `pad:` does.

- [ ] **Step 2: Verify headless** with `dev/shoot.py` on `/launcher?preview`: steps `showStream('Apple TV')` → shot shows the pill; `onPad('stream:off')` → `#stream` hidden; `showStream('<b>x</b>')` → `#stream.textContent === "Streaming to <b>x</b>"`; return any page errors (listener added in the first step) — expected `[]`.

- [ ] **Step 3: Commit** `web/launcher.html`: "Header pill while streaming to another screen".

### Task 4: Go live and record

- [ ] **Step 1:** Restart the server (scheduled task) and reload the TV page, only if no game is running (`tasklist | grep -ci GTA5_Enhanced.exe` = 0).
- [ ] **Step 2:** `stream.cmd on "Apple TV"` → the TV header shows the pill; `stream.cmd off` → gone.
- [ ] **Step 3:** Add a SESSION.md line: what was built, the prep-command decision, and that a real Sunshine/Moonlight session is untested until the user installs Sunshine. Commit.
