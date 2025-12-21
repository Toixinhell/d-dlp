"""GUI tool to back up Discord channel messages and attachments.

This module provides a Tkinter based interface that allows a user to:

* Authenticate with a Discord bot or user token.
* Choose the channel that should be archived.
* Decide whether to export only message text, only media (images and videos), or both.
* Select the directory where the export will be created.

The implementation intentionally sticks to the HTTP REST API instead of a
full event driven Discord client so that the script can be run on demand
without needing gateway intents.  The REST calls honour Discord's
rate-limit headers and back off when necessary.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


DISCORD_API_ROOT = "https://discord.com/api/v10"

BackupMode = Literal["text", "media", "both"]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg"}

TOKEN_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"mfa\.[\w-]{20,}"),
    re.compile(r"[\w-]{24}\.[\w-]{6}\.[\w-]{27}"),
)


def discover_discord_tokens() -> List[Tuple[str, str]]:
    """Collect likely Discord tokens from the environment and desktop client caches."""

    candidates: List[Tuple[str, str]] = []
    seen: set[str] = set()

    env_token = os.environ.get("DISCORD_TOKEN", "").strip()
    if env_token:
        candidates.append((env_token, "environment variable DISCORD_TOKEN"))
        seen.add(env_token)

    for leveldb_dir in _discord_leveldb_paths():
        for token in _extract_tokens_from_leveldb(leveldb_dir):
            if token not in seen:
                candidates.append((token, str(leveldb_dir)))
                seen.add(token)

    return candidates


def _discord_leveldb_paths() -> Iterable[Path]:
    roots: List[Path] = []

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata))
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support")
    else:
        roots.extend([
            Path.home() / ".config",
            Path.home() / ".var" / "app" / "com.discordapp.Discord" / "config",
            Path.home() / ".var" / "app" / "dev.vencord.Vesktop" / "config",
        ])

    folder_names = (
        "discord",
        "Discord",
        "discordcanary",
        "DiscordCanary",
        "discordptb",
        "DiscordPTB",
        "Vencord",
        "vencord",
        "VencordDesktop",
        "vencorddesktop",
        "Vesktop",
        "vesktop",
    )

    for root in roots:
        for name in folder_names:
            leveldb_dir = root / name / "Local Storage" / "leveldb"
            if leveldb_dir.is_dir():
                yield leveldb_dir


def _extract_tokens_from_leveldb(directory: Path) -> Iterable[str]:
    tokens: List[str] = []
    for suffix in ("*.ldb", "*.log"):
        for file_path in directory.glob(suffix):
            tokens.extend(_extract_tokens_from_file(file_path))
    return tokens


def _extract_tokens_from_file(file_path: Path) -> List[str]:
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    found: List[str] = []
    for pattern in TOKEN_PATTERNS:
        found.extend(pattern.findall(content))
    return found


class DiscordAPIError(RuntimeError):
    """Raised when the Discord API returns an unrecoverable error."""


@dataclass
class MessageRecord:
    """A simplified representation of a Discord message."""

    id: str
    author: str
    timestamp: str
    content: str
    attachments: List[Dict[str, object]]


class DiscordBackupClient:
    """HTTP client for fetching Discord channel history."""

    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "User-Agent": "discord-backup-gui (https://github.com/, 0.1)",
        })

    def iter_messages(self, channel_id: str) -> Iterable[MessageRecord]:
        """Yield messages in reverse chronological order.

        The function paginates through the Discord REST API and respects
        rate-limit headers.  Messages are yielded newest to oldest to avoid
        loading all records into memory at once.
        """

        url = f"{DISCORD_API_ROOT}/channels/{channel_id}/messages"
        params: Dict[str, object] = {"limit": 100}

        while True:
            response = self.session.get(url, params=params)
            if response.status_code == 429:
                self._handle_ratelimit(response)
                continue

            if not response.ok:
                raise DiscordAPIError(
                    f"Discord API returned {response.status_code}: {response.text}"
                )

            payload = response.json()
            if not payload:
                break

            for raw_message in payload:
                yield MessageRecord(
                    id=raw_message["id"],
                    author=raw_message["author"]["username"],
                    timestamp=raw_message["timestamp"],
                    content=raw_message.get("content", ""),
                    attachments=raw_message.get("attachments", []),
                )

            params["before"] = payload[-1]["id"]

    def download_attachment(
        self, attachment: Dict[str, object], directory: Path
    ) -> Optional[Path]:
        """Download the attachment if it looks like an image or video.

        Returns the local file path if the attachment is downloaded, otherwise
        ``None``.
        """

        url = attachment.get("url")
        filename = attachment.get("filename")
        media_kind = self._attachment_media_kind(attachment)

        if not url or not filename or media_kind is None:
            return None

        target = directory / filename
        response = self.session.get(url, stream=True)
        if response.status_code == 429:
            self._handle_ratelimit(response)
            return self.download_attachment(attachment, directory)

        if not response.ok:
            raise DiscordAPIError(
                f"Failed to download attachment {url}: {response.status_code}"
            )

        with target.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=65536):
                file_handle.write(chunk)

        return target

    @staticmethod
    def _attachment_media_kind(attachment: Dict[str, object]) -> Optional[str]:
        """Classify the attachment as image/video when possible."""

        content_type = str(attachment.get("content_type") or "").lower()
        filename = str(attachment.get("filename") or "")
        suffix = Path(filename).suffix.lower()

        if content_type.startswith("image/") or suffix in IMAGE_EXTENSIONS:
            return "image"
        if content_type.startswith("video/") or suffix in VIDEO_EXTENSIONS:
            return "video"
        return None

    @staticmethod
    def _handle_ratelimit(response: requests.Response) -> None:
        reset_after = response.headers.get("X-RateLimit-Reset-After")
        try:
            delay = float(reset_after) if reset_after is not None else 1.0
        except ValueError:
            delay = 1.0
        time.sleep(max(delay, 0.5))


class BackupController:
    """Coordinate the backup process and update the user interface."""

    def __init__(self, root: tk.Tk, log_widget: ScrolledText):
        self.root = root
        self.log_widget = log_widget

    def log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.configure(state="disabled")
        self.log_widget.see(tk.END)

    def run_backup(
        self,
        token: str,
        channel_id: str,
        output_dir: Path,
        mode: BackupMode,
    ) -> None:
        thread = threading.Thread(
            target=self._backup_thread,
            args=(token.strip(), channel_id.strip(), output_dir, mode),
            daemon=True,
        )
        thread.start()

    def _backup_thread(
        self,
        token: str,
        channel_id: str,
        output_dir: Path,
        mode: BackupMode,
    ) -> None:
        if not token or not channel_id:
            self._async_error("Token and Channel ID are required.")
            return

        try:
            client = DiscordBackupClient(token)
            backup_dir = output_dir / f"discord-channel-{channel_id}"
            backup_dir.mkdir(parents=True, exist_ok=True)

            text_records: List[MessageRecord] = []

            for message in client.iter_messages(channel_id):
                if mode in ("text", "both"):
                    text_records.append(message)

                if mode in ("media", "both") and message.attachments:
                    for attachment in message.attachments:
                        try:
                            downloaded = client.download_attachment(attachment, backup_dir)
                        except DiscordAPIError as error:
                            self._async_error(str(error))
                            return
                        if downloaded:
                            kind = client._attachment_media_kind(attachment) or "file"
                            self._async_log(f"Downloaded {kind}: {downloaded.name}")

            if text_records and mode in ("text", "both"):
                self._write_text_backup(text_records, backup_dir)

            self._async_log("Backup finished successfully.")
        except DiscordAPIError as error:
            self._async_error(str(error))
        except requests.RequestException as error:
            self._async_error(f"Network error: {error}")

    def _write_text_backup(self, messages: List[MessageRecord], backup_dir: Path) -> None:
        text_path = backup_dir / "messages.json"
        serialised = [
            {
                "id": record.id,
                "author": record.author,
                "timestamp": record.timestamp,
                "content": record.content,
                "attachments": record.attachments,
            }
            for record in reversed(messages)
        ]

        text_path.write_text(json.dumps(serialised, indent=2, ensure_ascii=False), encoding="utf-8")
        self._async_log(f"Saved text backup to {text_path}")

    def _async_log(self, message: str) -> None:
        self.root.after(0, lambda: self.log(message))

    def _async_error(self, message: str) -> None:
        def callback() -> None:
            self.log(f"Error: {message}")
            messagebox.showerror("Backup failed", message)

        self.root.after(0, callback)


class BackupApp(tk.Tk):
    """Tkinter application wiring together inputs and controller."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Discord Backup Tool")
        self.resizable(False, False)

        self.token_var = tk.StringVar()
        self.channel_var = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home()))
        self.mode_var: tk.StringVar = tk.StringVar(value="both")

        self.log_widget = ScrolledText(self, width=80, height=20, state="disabled")
        self.controller = BackupController(self, self.log_widget)

        self._build_form()

    def _build_form(self) -> None:
        padding_options = {"padx": 10, "pady": 5, "sticky": "w"}

        ttk.Label(self, text="Discord Token:").grid(row=0, column=0, **padding_options)
        token_frame = ttk.Frame(self)
        token_frame.grid(row=0, column=1, sticky="we", padx=10, pady=5)
        ttk.Entry(token_frame, textvariable=self.token_var, width=60, show="*").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(token_frame, text="Auto-detect", command=self._auto_detect_token).pack(
            side=tk.LEFT, padx=5
        )

        ttk.Label(self, text="Channel ID:").grid(row=1, column=0, **padding_options)
        ttk.Entry(self, textvariable=self.channel_var, width=30).grid(
            row=1, column=1, **padding_options
        )

        ttk.Label(self, text="Output directory:").grid(row=2, column=0, **padding_options)
        directory_frame = ttk.Frame(self)
        directory_frame.grid(row=2, column=1, sticky="we", padx=10, pady=5)
        ttk.Entry(directory_frame, textvariable=self.output_dir, width=45).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(directory_frame, text="Browse", command=self._choose_directory).pack(side=tk.LEFT, padx=5)

        ttk.Label(self, text="Backup mode:").grid(row=3, column=0, **padding_options)
        mode_frame = ttk.Frame(self)
        mode_frame.grid(row=3, column=1, sticky="w", padx=10, pady=5)
        for text, value in (
            ("Text only", "text"),
            ("Media only (images & videos)", "media"),
            ("Text and media", "both"),
        ):
            ttk.Radiobutton(mode_frame, text=text, value=value, variable=self.mode_var).pack(side=tk.LEFT, padx=5)

        ttk.Button(self, text="Start backup", command=self._start_backup).grid(
            row=4, column=0, columnspan=2, pady=10
        )

        ttk.Label(self, text="Log:").grid(row=5, column=0, padx=10, sticky="nw")
        self.log_widget.grid(row=5, column=1, padx=10, pady=(0, 10))

    def _choose_directory(self) -> None:
        path = filedialog.askdirectory(initialdir=self.output_dir.get() or str(Path.home()))
        if path:
            self.output_dir.set(path)

    def _start_backup(self) -> None:
        output = Path(self.output_dir.get()).expanduser()
        mode = self.mode_var.get() or "both"
        self.controller.log("Starting backup…")
        self.controller.run_backup(
            token=self.token_var.get(),
            channel_id=self.channel_var.get(),
            output_dir=output,
            mode=mode,  # type: ignore[arg-type]
        )

    def _auto_detect_token(self) -> None:
        tokens = discover_discord_tokens()
        if not tokens:
            messagebox.showinfo(
                "Token not found",
                "Could not auto-detect a Discord token. Please enter it manually.",
            )
            self.controller.log("Token auto-detect failed.")
            return

        token, source = tokens[0]
        self.token_var.set(token)
        self.controller.log(f"Loaded token from {source}.")

        if len(tokens) > 1:
            extra_sources = ", ".join(src for _value, src in tokens[1:])
            self.controller.log(f"Additional tokens detected from: {extra_sources}")


def main() -> None:
    app = BackupApp()
    app.mainloop()


if __name__ == "__main__":
    main()
