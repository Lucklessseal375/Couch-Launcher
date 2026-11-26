# Play on the Apple TV in another room (Vibepollo + Moonlight)

Couch streams to the Apple TV through two free programs: **Vibepollo** on the PC sends the picture and sound, **Moonlight** on the Apple TV shows it and sends your controller back. You set this up once; after that you open Moonlight on the Apple TV, pick **Couch**, and play. Home network only.

## 1. On the PC: done by the installer
`install-couch.ps1` installs [Vibepollo](https://github.com/Nonary/Vibepollo) (a fork of Sunshine, version 2.18.9) with its own controller driver set to a PS5 (DualSense) controller, and adds the **Couch** app to it (with the commands that tell Couch a stream started or ended). If the PC has Sunshine, Vibepollo replaces it. The one thing left for you on the PC:

- Open Vibepollo's settings page at <https://localhost:47990> (or Couch's PC row → **Streaming** → Open Vibepollo settings) and create a username and password if it asks. Couch only keeps them if you choose **Connect to Vibepollo**, encrypted for your Windows account.

Start with **1080p, 60 FPS** in Moonlight: on Wi-Fi a lower resolution keeps the stream smooth. You can raise it later.

## 2. If you set Vibepollo up by hand instead
Turn Vibepollo's **virtual display** off (`virtual_display_mode = disabled`), or Moonlight shows an empty desktop instead of Couch.

In Vibepollo's page, **Applications → Add New**: name `Couch`, leave **Command** empty, and add one **Command Preparations** row: Do `"<Couch folder>\couch-remote\stream.cmd" on "Apple TV"`, Undo `"<Couch folder>\couch-remote\stream.cmd" off`. If Couch doesn't react when a stream starts, wrap both in `cmd /C "..."`.

When a stream starts, Couch comes to the front, shows **Streaming to Apple TV** in its header, and stops moving the sound back to the living-room TV. When it ends, everything goes back to normal.

## 3. On the Apple TV
1. Install **Moonlight Game Streaming** from the App Store.
2. Open it. It finds the PC on your home network; select it. It shows a 4-digit PIN.
3. On the PC, in Vibepollo's page, go to **PIN** and type that PIN.
4. Pair your PS5 controller to the Apple TV: Apple TV **Settings → Remotes and Devices → Bluetooth**, then hold **PS + Create** on the controller until its light flashes, and select it.

## 4. Play
On the Apple TV: Moonlight → your PC → **Couch**. Use the controller as usual.

On the living-room TV, Couch's PC row has a **Streaming** tile: it shows whether Vibepollo is running and what it's streaming to, opens Vibepollo's settings page on that screen (use a mouse and keyboard there), and has **End stream** for when Couch still thinks a stream is on. Vibepollo itself starts with Windows; restart it from its own page (Troubleshooting) if ever needed.

**When you're done**, just leave Moonlight: Couch reads Vibepollo's log and notices the disconnect within a few seconds (and notices when you rejoin). Choosing **Quit App** in Moonlight also closes the session on the PC.

**Only one controller at a time:** games listen to the first controller. Turn the living-room PS5 controller off (Couch's PC row → Turn off controller) while you play from the other room, and in Moonlight's settings give each controller its own slot (multi-controller "Auto"), so the Siri Remote doesn't flatten your sticks.

## Known limits
- **Adaptive triggers don't reach the Apple TV.** The PC sees a PS5 controller, but the Apple TV Moonlight app doesn't apply trigger effects. Playing on the PC with the controller connected to it directly doesn't go through Vibepollo at all.
- If Couch restarts during a stream, it forgets that a stream is on until the next one starts (the header pill and the audio stand-down come back then).
- Sound and picture quality depend on your Wi-Fi. A wired connection on the PC, the Apple TV, or both helps most.
- The living-room TV shows the same picture during a stream; turn it off if you like.
