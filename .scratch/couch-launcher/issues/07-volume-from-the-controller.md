# Idea: TV volume from the controller

Status: needs-triage

Volume today means the TV remote or the phone. L2/R2 are free in the launcher (Apple maps no UI action to triggers). The server already sends keys, so L2/R2 could send Windows volume down/up (`VK_VOLUME_DOWN`/`UP`) while the launcher is in front, with a small level toast. About 15 lines. Only works if the PC's output is what the TV plays (HDMI audio), which it is today.
