# Idea: show the controller's battery on the launcher

Status: needs-triage

The server already reads the DualSense through pygame/SDL, which can report a battery level (empty/low/medium/full). The launcher could show a small battery icon next to the clock, like the PS5 does, so you know when to charge.

About 15 lines (server sends the level on the existing event stream; launcher draws an icon). Say "do 05" if you want it.

## Comments
