# Idea: show the controller's battery on the launcher

Status: resolved

The server already reads the DualSense through pygame/SDL, which can report a battery level (empty/low/medium/full). The launcher could show a small battery icon next to the clock, like the PS5 does, so you know when to charge.

About 15 lines (server sends the level on the existing event stream; launcher draws an icon). Say "do 05" if you want it.

## Comments

- 2026-11-21: Done. The server checks every 5 s and sends `pad:<level>` on the event stream (weakest pad wins; new pages get the current state on connect). The launcher shows a line under the date only when it matters: "No controller", "Controller battery half/low/empty" (low and empty in red), or "Controller charging". Full shows nothing. Test: `PadStatusTest`.
