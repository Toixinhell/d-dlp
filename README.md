# Discord backup GUI

This repository contains a small Tkinter application that can export the
history of a Discord text channel.

## Features

* Choose between saving **text only**, **image attachments only**, or **both**.
* Uses the Discord REST API so it runs on-demand without gateway intents.
* Stores message content in `messages.json` and downloads images into the
  selected output directory.

> **Note:** exporting chats requires a valid Discord bot token with the
> `Read Message History` and `View Channel` permissions for the target channel
> or a user token. Keep your token safe and never share it.

## Running the app

1. Install the single dependency:

   ```bash
   python -m pip install requests
   ```

2. Start the GUI:

   ```bash
   python discord_backup_gui.py
   ```

3. Fill in your token, channel ID, destination directory and the desired
   backup mode, then click **Start backup**.
