# Design review: Couch launcher (apple-design skill, 2026-11-21)

## Summary
A 10-foot, controller-driven launcher for a Windows PC on a TV. Its job: get from the couch to a game or app in a few presses. It is remembered by the Steel Ball Run poster, the pink Couch logo, the spinning steel ball on the focused tile and ゴゴゴ. That point of view stays. Rating before this pass: **Good** (no Critical findings, two High). After: **Good to Excellent**; what's left is in issues 06–09.

Scope: this is a web page in Edge, so Apple's principles and foundations apply (accessibility, motion, layout, writing, game controls, focus), not tvOS/macOS conventions. tvOS-only pages aren't in the skill, so the TV text sizes below are my judgment, not a citation.

## Fixed in this pass

| # | Severity | Finding | Why | Change |
|---|---|---|---|---|
| 1 | High | No answer to Reduce Motion: the ball spins forever, ゴゴゴ shakes, the title slides with a skew. | `accessibility.md › Motion`: "ensure your app or game responds by reducing automatic and repetitive animations, including zooming, scaling, and peripheral motion"; "Replacing transitions … with fades". | `@media (prefers-reduced-motion: reduce)`: no spin, shake, slide or zoom; ゴゴゴ becomes a fade. Edge follows Windows *Settings › Accessibility › Visual effects › Animation effects*, which is on today, so nothing changes now. |
| 2 | High (judgment) | Small text for a TV across a room: PC tile labels 1.6vh (17 px at 1080p), footer 1.8vh, date 1.7vh. | `designing-for-games.md › Look stunning on every display`: "Make sure text is always legible". | PC labels 1.9vh, date 1.9vh, footer 2vh. |
| 3 | Medium | "○ Back" shown on the home screen, where ○ does nothing. | `game-controls.md › Touch controls`: "hide controls when an action isn't available or relevant". | ○ Back hint shows only while a dialog is open. |
| 4 | Medium | Sleep asks "Put the PC to sleep?" first. | `alerts.md › Best practices`: "Avoid displaying alerts for common, undoable actions". Waking undoes sleep. | Sleep goes straight to sleep with a "Sleeping…" toast. Restart and Shut down keep their dialogs (unsaved work in other apps is lost), Cancel still focused first. |
| 5 | Medium | "Couch server isn't running." with no next step, though the page already retries. | `writing.md`, `feedback.md`: say what happened and what happens next. | "Couch server isn't running. Trying again…" |
| 6 | Medium | Shoulder buttons do nothing. | `game-controls.md › Physical controllers` maps L1/R1 to moving between screens or sections. Up/down already moves between rows, so here L1/R1 move a page along the row instead (my call). | L1/R1 (PageUp/PageDown on a keyboard) jump 5 tiles. |

## New features
- **Controller battery** (issue 05, resolved): under the date, only when it matters: "No controller", "Controller battery half/low/empty" (low/empty in red), "Controller charging".
- **Idle screen**: after 10 minutes with no input the launcher dims to black with a small clock that moves every minute, so the TV isn't shown a still, bright image for hours. The next press only wakes it; it doesn't move or launch anything.
- **L1/R1 paging** (row 6 above).

## What works (keep)
- The poster, logo, steel ball and ゴゴゴ: one loud place, everything else quiet (`branding.md`: brand defers to content).
- PS5 layout and button meanings: ✕ select, ○ back, coloured glyphs that match the DualSense (`game-controls.md`: "use the connected controller's labeling scheme").
- Nothing selected at start, so ✕ can't launch by accident; the pill appears with the first move.
- Dialogs: one short task, Cancel focused first on destructive actions, verbs on buttons.
- Games sorted by last played; "Loading games…" shows at once (`loading.md`: "Show something as soon as possible").

## Feature ideas (filed, not built)
- 06 Resume / Close the running game: **done** (see the issue).
- 07 TV volume on L2/R2: won't do, not needed.
- 08 □ options on a tile: hide a game, pin it to the front: **done** (see the issue).
- 09 Show when a Steam game is updating instead of launching into Steam's download page.
- Real app logos instead of name-only tiles (in PICKUP.md, needs a one-time icon extraction and a download OK).
