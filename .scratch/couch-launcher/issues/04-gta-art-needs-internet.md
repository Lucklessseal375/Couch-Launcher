# GTA V Enhanced's cover and backdrop need the internet

Status: resolved

The GTA tile's pictures load from Steam's image server each time (`apps.json` → `games`). Offline, or right after boot before Wi-Fi is up, the tile shows just the name.

Fix: save the two pictures into `couch-remote\web\` once and point `apps.json` at the local copies (about 0.8 MB). Claude needs your OK to download them. Say "do 04".

## Comments

- 2026-11-21: Done (the user said to stop asking). Both pictures are in `couch-remote/web/img/` (0.8 MB), served at `/img/...`, and apps.json points there.
