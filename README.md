# Discord backup GUI

This repository contains a small Tkinter application that can export the
history of a Discord text channel.

## Features

* Choose between saving **text only**, **media only** (images and videos), or **both**.
* Uses the Discord REST API so it runs on-demand without gateway intents.
* Stores message content in `messages.json` and downloads attachments into the
  selected output directory.

> **Note:** exporting chats requires a valid Discord bot token with the
> `Read Message History` and `View Channel` permissions for the target channel
> or a user token. Keep your token safe and never share it.

## Running the app

1. Install the Python dependency:

   ```bash
   python -m pip install -r requirements.txt
   ```

2. Start the GUI:

   ```bash
   python discord_backup_gui.py
   ```

3. If you are running from the VSCodium Flatpak terminal, start it through the
   host Python so Tkinter can load the host GUI libraries:

   ```bash
   flatpak-spawn --host /usr/bin/python3 /home/toix/Documents/github/d-dlp/discord_backup_gui.py
   ```

4. Fill in your token, channel ID, destination directory and the desired
   backup mode, then click **Start backup**.

Tkinter is part of the Python standard library, but Linux distributions package
its native GUI libraries separately. If `import tkinter` fails outside Flatpak,
install your distribution's Tkinter package, for example `python3-tk` on
Debian/Ubuntu.

## Building a standalone executable

The repository includes a helper script that wraps [PyInstaller] so you can
create a single-file executable of the GUI.  This is handy when you want to
start the program without invoking Python manually.

1. Install the additional build dependency:

   ```bash
   python -m pip install pyinstaller
   ```

2. Run the build helper from the repository root:

   ```bash
   python build_executable.py
   ```

3. The generated binary will be available in the `dist/` directory (for
   example `dist/discord-backup-gui` on Linux and `dist/discord-backup-gui.exe`
   on Windows).  You can copy that file anywhere and run it directly.

[PyInstaller]: https://pyinstaller.org
