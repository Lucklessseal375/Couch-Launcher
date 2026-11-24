# Couch

A PS5-style, controller-driven launcher for a Windows PC on a TV, with a Steel Ball Run look. Pick games and apps with a PlayStation controller, control the PC from your phone, and stream to another TV in the house. Private repo, for the PCs at home.

## Set up Couch on another PC

1. **Download it.** On GitHub: **Code → Download ZIP**, then unzip it to `Documents\CouchSetup` (or `git clone` it there).
2. **Run the installer.** In that folder, double-click **Install Couch.cmd**. Click **Yes** when Windows asks for admin.
   It installs Python and pygame if needed, makes Couch start when you sign in, allows the phone remote through the firewall, installs Sunshine for streaming (with the Couch app added), and adds a **Couch** shortcut to the desktop. The window stays open at the end so you can read what it did.
3. **Connect the controller.** Pair a PS5 controller over Bluetooth (hold **PS + Create** until it flashes, then Settings → Bluetooth & devices → Add device), or plug it in with USB.
4. **Check your games.** Steam games show up by themselves. Other apps and games are listed in `couch-remote\apps.json`; tiles for programs a PC doesn't have are hidden on that PC (`"needs": "<path>"` hides an entry when that path is missing).
5. **Optional extras:** weather (`couch-remote\config.json` → `"weather": {"city": "…"}`), music clips in `couch-remote\web\audio`, and streaming to another TV: create a Sunshine login and pair Moonlight (`docs/streaming-setup.md`).

To stop Couch starting at sign-in: `Unregister-ScheduledTask -TaskName 'Couch Launcher' -Confirm:$false`.

## What's here

| Path | What it is |
| --- | --- |
| `couch-remote/` | Couch itself: `server.py` (Python, standard library + pygame), the TV page `web/launcher.html`, the phone remote `web/remote.html`, tests in `tests/` |
| `Install Couch.cmd`, `install-couch.ps1` | Sets Couch up on a PC (above); the .cmd runs the .ps1 |
| `docs/streaming-setup.md` | Play on another TV with Sunshine + Moonlight |
| `couch-setup.ps1` | Old one-off Windows tuning for the main PC only (restore point, startup apps). Not needed for Couch |
| `SESSION.md`, `PICKUP.md`, `.scratch/`, `docs/superpowers/` | Working notes from building Couch |

Run the tests from `couch-remote`: `python -m unittest discover -s tests`.

Never committed (git-ignored): Sunshine login (`couch-remote/cache/`), browser sign-ins (`couch-remote/profiles/`), `choices.json`, logs.
