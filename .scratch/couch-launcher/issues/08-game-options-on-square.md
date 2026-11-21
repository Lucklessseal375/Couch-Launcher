# Idea: options for a tile on the □ button (hide, pin)

Status: resolved

Every Steam game shows up, including ones you never play (`hide_steam_apps` in apps.json needs editing by hand). A □ press could open a small dialog for the focused tile: "Hide from launcher", "Pin to front", "Cancel". The server would save the choice to apps.json (`hide_steam_apps`, a new `pinned` list). About 50 lines. Hidden games need a way back: a "Show hidden games" item in the PC row.

## Comments

- 2026-11-21: Done, a bit differently from the plan above. The choices go to `couch-remote/choices.json` (`hidden`, `pinned`; made on first use) instead of apps.json, so the hand-edited apps.json is never rewritten. It works for every game in the row, Epic's GTA included, keyed by `id` or `steam:<appid>`. □ on a game opens Pin to front (or Unpin) / Hide / Cancel; newest pin goes first. A "Hidden games" tile shows up in the PC row while something is hidden; Show all brings them all back and moves the selection to the Games row (otherwise Sleep, which doesn't ask, slides under the cursor). The phone remote gets the same list. Server checks that the game exists. Test: `ChoicesTest`. Checked in the preview by calling the functions (no tile presses); not yet tried with the controller.
