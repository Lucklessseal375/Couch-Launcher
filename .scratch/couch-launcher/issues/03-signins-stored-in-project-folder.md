# YouTube/Netflix sign-ins are stored inside the project folder

Status: resolved

`couch-remote\profiles\` holds the Edge profiles (cookies = sign-ins) for the launcher, YouTube and Netflix. The folder also has your poster. If the folder is ever zipped, shared or put on GitHub, the logins go with it.

Fix (one line in `server.py`): `PROFILES = Path(os.environ["LOCALAPPDATA"]) / "CouchRemote" / "profiles"`.

Decision needed: moving it means signing in to YouTube/Netflix once more. Say "do 03" and Claude will make the change.

## Comments

- 2026-11-21: No longer needed. The YouTube and Netflix tiles were removed (games only) and their Edge profiles moved to the Recycle Bin. Only the launcher's profile is left, with no sign-ins. Reopen if a website tile with a sign-in is added back.
