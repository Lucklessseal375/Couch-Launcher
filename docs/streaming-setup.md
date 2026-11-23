# Play on the Apple TV in another room (Sunshine + Moonlight)

Couch streams to the Apple TV through two free programs: **Sunshine** on the PC sends the picture and sound, **Moonlight** on the Apple TV shows it and sends your controller back. You set this up once; after that you open Moonlight on the Apple TV, pick **Couch**, and play. Home network only.

## 1. On the PC: install Sunshine
1. Download the Windows installer from Sunshine's official releases page: <https://github.com/LizardByte/Sunshine/releases> (the `.exe` for Windows, from LizardByte).
2. Run it and accept its prompts (it asks for admin rights and adds a firewall rule for your home network).
3. Open Sunshine's settings page at <https://localhost:47990> and create a Sunshine username and password when it asks. Couch never sees or stores them.
4. Start with **1080p, 60 FPS**: the PC is on Wi-Fi, and a lower resolution keeps the stream smooth. You can raise it later.

## 2. In Sunshine: add Couch as an app
In Sunshine's page, go to **Applications → Add New**:
- **Application Name:** `Couch`
- **Command:** leave empty (it streams the screen Couch is on).
- **Command Preparations:** add one row:
  - **Do:** `"C:\Users\eli\Documents\CouchSetup\couch-remote\stream.cmd" on "Apple TV"`
  - **Undo:** `"C:\Users\eli\Documents\CouchSetup\couch-remote\stream.cmd" off`
- Save.
- Keep the name in quotes plain: letters, numbers and spaces only.
- If Couch doesn't react when a stream starts, change both commands to the `cmd /C` form, for example Do: `cmd /C ""C:\Users\eli\Documents\CouchSetup\couch-remote\stream.cmd" on "Apple TV""`.

When a stream starts, Couch comes to the front, shows **Streaming to Apple TV** in its header, and stops moving the sound back to the living-room TV. When it ends, everything goes back to normal.

## 3. On the Apple TV
1. Install **Moonlight Game Streaming** from the App Store.
2. Open it. It finds the PC on your home network; select it. It shows a 4-digit PIN.
3. On the PC, in Sunshine's page, go to **PIN** and type that PIN.
4. Pair your PS5 controller to the Apple TV: Apple TV **Settings → Remotes and Devices → Bluetooth**, then hold **PS + Create** on the controller until its light flashes, and select it.

## 4. Play
On the Apple TV: Moonlight → your PC → **Couch**. Use the controller as usual.

On the living-room TV, Couch's PC row has a **Streaming** tile: it shows whether Sunshine is running and what it's streaming to, opens Sunshine's settings page on that screen (use a mouse and keyboard there), and has **End stream** for when Couch still thinks a stream is on. Sunshine itself starts with Windows; restart it from its own page (Troubleshooting) if ever needed.

**When you're done**, just leave Moonlight: Couch reads Sunshine's log and notices the disconnect within a few seconds (and notices when you rejoin). Choosing **Quit App** in Moonlight also closes the session on the PC.

**Only one controller at a time:** games listen to the first controller. Turn the living-room PS5 controller off (Couch's PC row → Turn off controller) while you play from the other room, and in Moonlight's settings give each controller its own slot (multi-controller "Auto"), so the Siri Remote doesn't flatten your sticks.

## Known limits
- If Couch restarts during a stream, it forgets that a stream is on until the next one starts (the header pill and the audio stand-down come back then).
- Sound and picture quality depend on your Wi-Fi. A wired connection on the PC, the Apple TV, or both helps most.
- The living-room TV shows the same picture during a stream; turn it off if you like.
