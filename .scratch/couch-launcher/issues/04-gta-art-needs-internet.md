# GTA V Enhanced's cover and backdrop need the internet

Status: ready-for-human

The GTA tile's pictures load from Steam's image server each time (`apps.json` → `games`). Offline, or right after boot before Wi-Fi is up, the tile shows just the name.

Fix: save the two pictures into `couch-remote\web\` once and point `apps.json` at the local copies (about 0.8 MB). Claude needs your OK to download them. Say "do 04".

## Comments
