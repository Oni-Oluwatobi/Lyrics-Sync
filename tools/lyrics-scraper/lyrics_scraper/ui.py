"""Tkinter desktop interface for the Gospel lyrics database builder.

Standard library only (``tkinter``, ``sqlite3``, ``subprocess``).  The window
drives the *same* CLI pipeline — fetch → parse → validate → dedupe → review →
export — by launching ``python -m lyrics_scraper`` in a child process, so the
builder keeps working from a terminal and from a GUI, and a crashing or
runaway crawl can always be stopped without taking the window down.

This module is part of the standalone builder: it is never imported by the
Lyric Sync application and is never collected into the installer.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import subprocess
import sys
import threading
import tkinter as tk
import urllib.parse
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PACKAGE_ROOT / "output"
SOURCES = ("auto", "opengospellyrics", "africangospellyrics", "gutenberg",
           "zionlyrics")
REVIEWS = ("", "clean", "flagged", "pending_review", "approved", "rejected")
COPYRIGHT = ("METADATA_ONLY", "PUBLIC_DOMAIN", "AUTHORIZED", "LICENSED",
             "USER_IMPORTED", "UNKNOWN")

SONG_COLUMNS = (
    ("title", "Title", 260),
    ("artist", "Artist", 150),
    ("source_site", "Source", 150),
    ("article_date", "Published", 92),
    ("sections", "Sec", 44),
    ("line_count", "Lines", 54),
    ("review_status", "Review", 104),
    ("warning_count", "Warn", 50),
)

SONG_QUERY = """
SELECT s.song_id, s.title, s.artist, s.source_site, s.article_date,
       s.review_status, s.include_lyrics, s.copyright_status, s.line_count,
       s.warning_count, s.source_url, s.article_url, s.artists,
       s.featured_artists, s.languages, s.language_confidence, s.countries,
       s.category, s.tags, s.author, s.year, s.taxonomy,
       (SELECT COUNT(DISTINCT section_order) FROM song_sections x
         WHERE x.song_id = s.song_id) AS sections
  FROM songs s
"""

COUNT_QUERIES = (
    ("songs", "SELECT COUNT(*) FROM songs"),
    ("sections", "SELECT COUNT(DISTINCT song_id || ':' || section_order) "
                 "FROM song_sections"),
    ("lyric_lines", "SELECT COUNT(*) FROM song_sections"),
    ("artists", "SELECT COUNT(*) FROM artists"),
    ("sources", "SELECT COUNT(*) FROM song_sources"),
    ("tags", "SELECT COUNT(*) FROM tags"),
    ("pages", "SELECT COUNT(*) FROM pages"),
    ("warnings", "SELECT COUNT(*) FROM validation_warnings"),
    ("flagged", "SELECT COUNT(*) FROM songs WHERE review_status = 'flagged'"),
    ("include_lyrics", "SELECT COUNT(*) FROM songs WHERE include_lyrics = 1"),
)


def _as_list(value) -> list:
    import json
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class Runner:
    """Runs one CLI command in a child process and queues its output."""

    def __init__(self) -> None:
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.last_code: int | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, args: list[str]) -> bool:
        if self.running:
            return False
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "lyrics_scraper", *args],
            cwd=str(PACKAGE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self) -> None:
        process = self.process
        code = -1
        try:
            if process is not None and process.stdout is not None:
                for line in process.stdout:
                    self.events.put(("line", line.rstrip("\n")))
                code = process.wait()
        except Exception as exc:                       # pragma: no cover
            self.events.put(("line", f"!! reader failed: {exc}"))
        self.last_code = code
        self.events.put(("done", code))

    def stop(self) -> None:
        if self.running and self.process is not None:
            self.events.put(("line", "!! stop requested — terminating run"))
            try:
                self.process.terminate()
            except OSError:                            # pragma: no cover
                pass


class App(tk.Tk):
    """The builder window: settings, command bar, log / songs / export."""

    def __init__(self, *, output_dir: str | Path = DEFAULT_OUTPUT,
                 source: str = "auto", delay: float = 1.0,
                 timeout: float = 30.0, cache_only: bool = False,
                 ignore_robots: bool = False) -> None:
        super().__init__()
        self.title("Lyric Sync — Gospel Lyrics Database Builder")
        self.geometry("1200x780")
        self.minsize(940, 620)

        self.output_dir_var = tk.StringVar(value=str(Path(output_dir)))
        self.source_var = tk.StringVar(value=source if source in SOURCES
                                       else "auto")
        self.delay_var = tk.StringVar(value=str(delay))
        self.timeout_var = tk.StringVar(value=str(timeout))
        self.cache_var = tk.BooleanVar(value=bool(cache_only))
        self.robots_var = tk.BooleanVar(value=bool(ignore_robots))
        self.url_var = tk.StringVar()
        self.limit_var = tk.StringVar(value="25")
        self.depth_var = tk.StringVar(value="1")
        self.filter_source_var = tk.StringVar()
        self.filter_review_var = tk.StringVar()
        self.filter_search_var = tk.StringVar()
        self.export_out_var = tk.StringVar(
            value=str(Path(output_dir) / "exports" / "exported.lsdb"))
        self.export_version_var = tk.StringVar(value="1.0.0")
        self.export_lyrics_var = tk.BooleanVar(value=False)
        self.export_flagged_var = tk.BooleanVar(value=False)
        self.export_overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="ready")
        self.counts_var = tk.StringVar(value="")
        self.selected_song_id: str | None = None

        self.runner = Runner()
        self._build_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        self._refresh_stats()
        self._refresh_songs()

    # -- layout ------------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style(self)
        for theme in ("vista", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TButton", padding=(10, 4))
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Counts.TLabel", font=("Segoe UI", 9))
        style.configure("Flagged.Treeview", foreground="#b00020")

    def _build(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        self._build_settings(root)
        self._build_commands(root)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, pady=(8, 0))
        self._build_log_tab(notebook)
        self._build_songs_tab(notebook)
        self._build_export_tab(notebook)
        self.notebook = notebook

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(6, 0))
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        ttk.Label(status, textvariable=self.counts_var,
                  style="Counts.TLabel").pack(side="right")

    def _build_settings(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="Settings", padding=(8, 6))
        frame.pack(fill="x")

        ttk.Label(frame, text="Output folder").grid(row=0, column=0,
                                                    sticky="w")
        ttk.Entry(frame, textvariable=self.output_dir_var,
                  width=44).grid(row=0, column=1, sticky="we", padx=(4, 8))
        ttk.Button(frame, text="Browse…",
                   command=self._choose_output).grid(row=0, column=2,
                                                     padx=(0, 8))

        ttk.Label(frame, text="Source").grid(row=0, column=3, sticky="w")
        ttk.Combobox(frame, textvariable=self.source_var, values=SOURCES,
                     state="readonly", width=20).grid(row=0, column=4,
                                                      padx=(4, 8))

        ttk.Label(frame, text="Delay (s)").grid(row=0, column=5, sticky="w")
        ttk.Entry(frame, textvariable=self.delay_var,
                  width=6).grid(row=0, column=6, padx=(4, 8))
        ttk.Label(frame, text="Timeout (s)").grid(row=0, column=7,
                                                  sticky="w")
        ttk.Entry(frame, textvariable=self.timeout_var,
                  width=6).grid(row=0, column=8, padx=(4, 8))

        ttk.Checkbutton(frame, text="Cache only", variable=self.cache_var
                        ).grid(row=0, column=9, padx=(0, 6))
        ttk.Checkbutton(frame, text="Ignore robots.txt",
                        variable=self.robots_var).grid(row=0, column=10)

        frame.columnconfigure(1, weight=1)

    def _build_commands(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="Run", padding=(8, 6))
        frame.pack(fill="x", pady=(6, 0))

        ttk.Entry(frame, textvariable=self.url_var).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        self.run_buttons: list[ttk.Button] = []

        for label, command in (
                ("Single", "single"), ("Article", "article")):
            button = ttk.Button(frame, text=label,
                                command=lambda c=command: self._run_fetch(c))
            button.pack(side="left", padx=2)
            self.run_buttons.append(button)

        ttk.Label(frame, text="limit").pack(side="left", padx=(8, 2))
        ttk.Spinbox(frame, from_=1, to=9999, textvariable=self.limit_var,
                    width=5).pack(side="left")
        button = ttk.Button(frame, text="Category",
                            command=lambda: self._run_fetch("category"))
        button.pack(side="left", padx=2)
        self.run_buttons.append(button)

        ttk.Label(frame, text="depth").pack(side="left", padx=(8, 2))
        ttk.Spinbox(frame, from_=0, to=5, textvariable=self.depth_var,
                    width=4).pack(side="left")
        button = ttk.Button(frame, text="Crawl",
                            command=lambda: self._run_fetch("crawl"))
        button.pack(side="left", padx=2)
        self.run_buttons.append(button)

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y",
                                                     padx=8)
        for label, command in (("Validate", "validate"),
                               ("Dedupe", "dedupe")):
            button = ttk.Button(frame, text=label,
                                command=lambda c=command: self._run(c))
            button.pack(side="left", padx=2)
            self.run_buttons.append(button)

        self.stop_button = ttk.Button(frame, text="Stop",
                                      command=self._stop, state="disabled")
        self.stop_button.pack(side="right", padx=2)

    def _build_log_tab(self, notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=" Log ")

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="Clear", command=self._clear_log).pack(
            side="left")
        ttk.Button(bar, text="Open output folder",
                   command=self._open_output).pack(side="left", padx=6)

        self.log = tk.Text(frame, wrap="none", height=20,
                           font=("Consolas", 9), state="disabled",
                           background="#1e1e1e", foreground="#d4d4d4",
                           insertbackground="#d4d4d4")
        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("cmd", foreground="#569cd6", font=(
            "Consolas", 9, "bold"))
        self.log.tag_configure("err", foreground="#f48771")
        self.log.tag_configure("warn", foreground="#dcdcaa")
        self.log.tag_configure("ok", foreground="#6a9955")
        self.log.tag_configure("head", foreground="#c586c0", font=(
            "Consolas", 9, "bold"))

    def _build_songs_tab(self, notebook) -> None:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=" Staged songs ")

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Source").pack(side="left")
        source_box = ttk.Combobox(bar, textvariable=self.filter_source_var,
                                  values=("", "OpenGospelLyrics",
                                          "African Gospel Lyrics"),
                                  width=18, state="readonly")
        source_box.pack(side="left", padx=(4, 10))
        source_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_songs())

        ttk.Label(bar, text="Review").pack(side="left")
        review_box = ttk.Combobox(bar, textvariable=self.filter_review_var,
                                  values=REVIEWS, width=14, state="readonly")
        review_box.pack(side="left", padx=(4, 10))
        review_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_songs())

        ttk.Entry(bar, textvariable=self.filter_search_var, width=26
                  ).pack(side="left", padx=(0, 6))
        self.filter_search_var.trace_add(
            "write", lambda *_: self._debounce_search())
        ttk.Button(bar, text="Refresh", command=self._refresh_songs
                   ).pack(side="left", padx=(0, 8))
        self.table_hint = ttk.Label(bar, text="")
        self.table_hint.pack(side="right")

        paned = ttk.Panedwindow(frame, orient="vertical")
        paned.pack(fill="both", expand=True)

        table_frame = ttk.Frame(paned)
        paned.add(table_frame, weight=3)
        columns = [key for key, _label, _width in SONG_COLUMNS]
        self.tree = ttk.Treeview(table_frame, columns=columns,
                                 show="headings", selectmode="browse")
        for key, label, width in SONG_COLUMNS:
            self.tree.heading(key, text=label)
            anchor = "e" if key in ("sections", "line_count",
                                    "warning_count") else "w"
            self.tree.column(key, width=width, anchor=anchor, stretch=(
                key == "title"))
        scroll = ttk.Scrollbar(table_frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("flagged", foreground="#b00020")
        self.tree.tag_configure("approved", foreground="#2e7d32")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        detail_frame = ttk.LabelFrame(paned, text="Details / review",
                                      padding=6)
        paned.add(detail_frame, weight=2)
        self.detail = tk.Text(detail_frame, wrap="word", height=8,
                              font=("Segoe UI", 9), state="disabled")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical",
                                      command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side="right", fill="y")
        self.detail.pack(fill="both", expand=True)

        actions = ttk.Frame(detail_frame)
        actions.pack(fill="x", pady=(6, 0))
        self.detail_buttons: list[ttk.Button] = []
        for label, command in (
                ("Approve", lambda: self._review("approve")),
                ("Reject", lambda: self._review("reject")),
                ("Flag", lambda: self._review("flag")),
                ("Lyrics ON", lambda: self._review("include_lyrics")),
                ("Lyrics OFF", lambda: self._review("no_lyrics"))):
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side="left", padx=2)
            self.detail_buttons.append(button)

        ttk.Label(actions, text="Copyright").pack(side="left",
                                                  padx=(12, 4))
        copyright_box = ttk.Combobox(actions, values=COPYRIGHT, width=16,
                                     state="readonly")
        copyright_box.set("PUBLIC_DOMAIN")
        copyright_box.pack(side="left")
        self.copyright_var = tk.StringVar(value="PUBLIC_DOMAIN")
        copyright_box.configure(textvariable=self.copyright_var)
        button = ttk.Button(
            actions, text="Set copyright",
            command=lambda: self._review("copyright"))
        button.pack(side="left", padx=6)
        self.detail_buttons.append(button)

    def _build_export_tab(self, notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=" Export ")

        form = ttk.Frame(frame)
        form.pack(fill="x")
        ttk.Label(form, text="Output .lsdb").grid(row=0, column=0,
                                                  sticky="w")
        ttk.Entry(form, textvariable=self.export_out_var
                  ).grid(row=0, column=1, sticky="we", padx=6, pady=3)
        ttk.Button(form, text="Browse…",
                   command=self._choose_export).grid(row=0, column=2)
        ttk.Label(form, text="Version").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.export_version_var, width=12
                  ).grid(row=1, column=1, sticky="w", padx=6, pady=3)
        form.columnconfigure(1, weight=1)

        flags = ttk.Frame(frame)
        flags.pack(fill="x", pady=4)
        ttk.Checkbutton(flags, text="Include lyric rows (requires each song "
                                    "to be marked for lyrics with a "
                                    "PUBLIC_DOMAIN / AUTHORIZED status)",
                        variable=self.export_lyrics_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="Include flagged songs",
                        variable=self.export_flagged_var).pack(anchor="w")
        ttk.Checkbutton(flags, text="Overwrite an existing file",
                        variable=self.export_overwrite_var).pack(anchor="w")

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=6)
        button = ttk.Button(actions, text="Export", command=self._export)
        button.pack(side="left")
        self.export_button = button
        ttk.Button(actions, text="Open output folder",
                   command=self._open_output).pack(side="left", padx=8)

        note = ttk.Label(
            frame, wraplength=880, foreground="#555555",
            text="The exporter copies the production database file as its "
                 "schema template (the production file is never opened for "
                 "writing), empties the copy and refills it. Without "
                 "'Include lyric rows' the export is metadata only — title, "
                 "artist, credits, sections and source.")
        note.pack(anchor="w", pady=(6, 0))

    # -- paths / connections ----------------------------------------------
    def output_dir(self) -> Path:
        path = Path(self.output_dir_var.get()).expanduser()
        if not path.is_absolute():
            path = PACKAGE_ROOT / path
        return path

    def staging_path(self) -> Path:
        return self.output_dir() / "staging" / "staging.sqlite"

    def _connect(self) -> sqlite3.Connection | None:
        path = self.staging_path()
        if not path.exists():
            return None
        connection = sqlite3.connect(path, timeout=2.5)
        connection.row_factory = sqlite3.Row
        return connection

    def global_args(self) -> list[str]:
        args = ["--output-dir", str(self.output_dir())]
        source = self.source_var.get()
        if source and source != "auto":
            args += ["--source", source]
        for flag, variable in (("--delay", self.delay_var),
                               ("--timeout", self.timeout_var)):
            args += [flag, str(variable.get()).strip() or "1"]
        if self.cache_var.get():
            args.append("--cache-only")
        if self.robots_var.get():
            args.append("--ignore-robots")
        return args

    # -- running -----------------------------------------------------------
    def _run(self, command: str, extra: list[str] | None = None) -> bool:
        if self.runner.running:
            messagebox.showinfo("Busy", "A command is already running — "
                               "press Stop first.", parent=self)
            return False
        args = self.global_args() + [command] + list(extra or [])
        self._set_busy(True)
        self._log(f"$ lyrics_scraper {' '.join(args)}", "cmd")
        self.status_var.set(f"running: {command}")
        if not self.runner.start(args):                # pragma: no cover
            self._set_busy(False)
            return False
        return True

    def _run_fetch(self, command: str) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL needed",
                                   "Enter the page URL to fetch.",
                                   parent=self)
            return
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            messagebox.showwarning(
                "Bad URL",
                "This does not look like a web address:\n\n"
                f"  {url}\n\nIt must start with https:// — check for a "
                "stray character (for example \"0https://\") before the "
                "scheme.",
                parent=self)
            return
        extra = [url]
        if command == "category":
            extra += ["--limit", str(self.limit_var.get().strip() or "25")]
        elif command == "crawl":
            extra += ["--depth", str(self.depth_var.get().strip() or "1")]
        self._run(command, extra)

    def _stop(self) -> None:
        self.runner.stop()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self.run_buttons:
            button.configure(state=state)
        self.export_button.configure(state=state)
        for button in self.detail_buttons:
            button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.runner.events.get_nowait()
                if kind == "line":
                    self._log(str(payload))
                elif kind == "done":
                    self._finished(int(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finished(self, code: int) -> None:
        self._set_busy(False)
        if code == 0:
            self._log(f"[exit {code}] command finished", "ok")
            self.status_var.set("ready")
        else:
            self._log(f"[exit {code}] command failed — see log above", "err")
            self.status_var.set(f"last command failed (exit {code})")
        self._refresh_stats()
        self._refresh_songs()

    # -- logging -----------------------------------------------------------
    def _log(self, text: str, tag: str | None = None) -> None:
        if not text:
            return
        near_end = self.log.yview()[1] >= 0.995
        self.log.configure(state="normal")
        tags = (tag,) if tag else ()
        if text.startswith("!!") or text.lower().startswith("traceback"):
            tags = tags + ("err",)
        elif "warning" in text.lower() and not tags:
            tags = ("warn",)
        self.log.insert("end", text + "\n", tags)
        self.log.configure(state="disabled")
        if near_end:
            self.log.see("end")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # -- stats -------------------------------------------------------------
    def _refresh_stats(self) -> None:
        connection = self._connect()
        if connection is None:
            self.counts_var.set("no staging database yet")
            return
        parts = []
        try:
            for label, query in COUNT_QUERIES:
                try:
                    value = connection.execute(query).fetchone()[0]
                except sqlite3.Error:
                    continue
                parts.append(f"{label} {value}")
        finally:
            connection.close()
        self.counts_var.set("  |  ".join(parts) or "empty staging database")

    # -- songs -------------------------------------------------------------
    def _filters(self) -> tuple[list[str], list[str]]:
        clauses: list[str] = []
        params: list[str] = []
        source = self.filter_source_var.get()
        if source:
            clauses.append("s.source_site = ?")
            params.append(source)
        review = self.filter_review_var.get()
        if review:
            clauses.append("s.review_status = ?")
            params.append(review)
        search = self.filter_search_var.get().strip()
        if search:
            clauses.append("(s.title LIKE ? OR s.artist LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        return clauses, params

    def _debounce_search(self) -> None:
        if getattr(self, "_search_after", None):
            self.after_cancel(self._search_after)
        self._search_after = self.after(350, self._refresh_songs)

    def _refresh_songs(self) -> None:
        connection = self._connect()
        self.tree.delete(*self.tree.get_children())
        if connection is None:
            self.table_hint.configure(text="no staging database yet — "
                                           "run a scrape first")
            return
        clauses, params = self._filters()
        query = SONG_QUERY + (f" WHERE {' AND '.join(clauses)}" if clauses
                              else "") + " ORDER BY s.created_at DESC, " \
                                        "s.song_id LIMIT 500"
        try:
            rows = connection.execute(query, params)
        except sqlite3.Error as exc:
            self.table_hint.configure(text=f"read failed: {exc}")
            connection.close()
            return
        count = 0
        for row in rows:
            values = [row[key] for key, _l, _w in SONG_COLUMNS]
            tags = ()
            if row["review_status"] == "flagged":
                tags = ("flagged",)
            elif row["review_status"] == "approved":
                tags = ("approved",)
            self.tree.insert("", "end", iid=row["song_id"], values=values,
                             tags=tags)
            count += 1
        connection.close()
        hidden = " (first 500)" if count == 500 else ""
        self.table_hint.configure(text=f"{count} song(s){hidden}")

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.selected_song_id = selection[0]
        self._load_detail(self.selected_song_id)

    def _load_detail(self, song_id: str) -> None:
        connection = self._connect()
        if connection is None:
            return
        try:
            row = connection.execute(
                SONG_QUERY + " WHERE s.song_id = ?", (song_id,)).fetchone()
            if row is None:
                return
            warnings = connection.execute(
                "SELECT severity, code, message FROM validation_warnings "
                "WHERE song_id = ? ORDER BY id",
                (song_id,)).fetchall()
            lines = connection.execute(
                "SELECT section_order, display_label, line_order, line_raw "
                "FROM song_sections WHERE song_id = ? "
                "ORDER BY section_order, line_order",
                (song_id,)).fetchall()
        finally:
            connection.close()

        text = self.detail
        text.configure(state="normal")
        text.delete("1.0", "end")
        artists = _as_list(row["artists"]) or [row["artist"]]
        featured = _as_list(row["featured_artists"])
        languages = _as_list(row["languages"])
        countries = _as_list(row["countries"])
        tags = _as_list(row["tags"])
        included = "yes" if row["include_lyrics"] else "no"
        fields = [
            ("Title", row["title"]),
            ("Artists", ", ".join(artists)),
            ("Featured", ", ".join(featured)),
            ("Published", row["article_date"]),
            ("Languages", f"{', '.join(languages) or '—'} "
                          f"(confidence: {row['language_confidence']})"),
            ("Countries", ", ".join(countries) or "—"),
            ("Category", row["category"] or "—"),
            ("Tags", ", ".join(tags) or "—"),
            ("Source", f"{row['source_site']} — {row['source_url']}"),
            ("Review", f"{row['review_status']}  "
                       f"(findings: {len(warnings)}, "
                       f"include lyrics: {included}, "
                       f"copyright: {row['copyright_status']})"),
        ]
        for label, value in fields:
            text.insert("end", f"{label:<11}", "head")
            text.insert("end", f"{value}\n")
        if warnings:
            text.insert("end", "\nFindings\n", "head")
            for warning in warnings:
                text.insert("end",
                            f"  [{warning['severity']}] {warning['code']}: "
                            f"{warning['message']}\n", "warn")
        text.insert("end", "\nLyric lines (exact source wording)\n", "head")
        section = None
        shown = 0
        for line in lines:
            if line["section_order"] != section:
                section = line["section_order"]
                text.insert("end", f"  [{line['display_label']}]\n", "cmd")
            if shown >= 120:
                text.insert("end", "  …\n")
                break
            text.insert("end", f"    {line['line_raw']}\n")
            shown += 1
        text.configure(state="disabled")

    # -- review ------------------------------------------------------------
    def _review(self, action: str) -> None:
        if not self.selected_song_id:
            messagebox.showinfo("Select a song",
                                "Pick a staged song first.",
                                parent=self)
            return
        updates: list[tuple[str, object]] = []
        if action == "approve":
            updates.append(("review_status = 'approved'", None))
        elif action == "reject":
            updates.append(("review_status = 'rejected'", None))
        elif action == "flag":
            updates.append(("review_status = 'flagged'", None))
        elif action == "include_lyrics":
            updates.append(("include_lyrics = 1", None))
        elif action == "no_lyrics":
            updates.append(("include_lyrics = 0", None))
        elif action == "copyright":
            updates.append(("copyright_status = ?", self.copyright_var.get()))
        assignments = ", ".join(part for part, _value in updates)
        values = [value for _part, value in updates if value is not None]
        path = self.staging_path()
        if not path.exists():
            return
        connection = sqlite3.connect(path, timeout=5.0)
        try:
            connection.execute(
                f"UPDATE songs SET {assignments} WHERE song_id = ?",
                (*values, self.selected_song_id))
            connection.commit()
        except sqlite3.Error as exc:
            messagebox.showerror("Update failed", str(exc), parent=self)
            return
        finally:
            connection.close()
        self.status_var.set(f"{action} → {self.selected_song_id}")
        self._refresh_stats()
        self._refresh_songs()
        self._load_detail(self.selected_song_id)

    # -- export ------------------------------------------------------------
    def _export(self) -> None:
        out = self.export_out_var.get().strip()
        if not out:
            messagebox.showwarning("Output needed",
                                   "Choose an output .lsdb path.",
                                   parent=self)
            return
        if Path(out).exists() and not self.export_overwrite_var.get():
            if not messagebox.askyesno(
                    "File exists",
                    f"{out} already exists.\nEnable overwrite and "
                    f"replace it?", parent=self):
                return
            self.export_overwrite_var.set(True)
        extra = ["--out", out, "--version",
                 self.export_version_var.get().strip() or "1.0.0"]
        if self.export_lyrics_var.get():
            extra.append("--include-lyrics")
        if self.export_flagged_var.get():
            extra.append("--include-flagged")
        if self.export_overwrite_var.get():
            extra.append("--overwrite")
        if self._run("export", extra):
            self.notebook.select(0)

    # -- helpers -----------------------------------------------------------
    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, mustexist=False,
            initialdir=str(self.output_dir()), title="Output folder")
        if chosen:
            self.output_dir_var.set(chosen)
            self._refresh_stats()
            self._refresh_songs()

    def _choose_export(self) -> None:
        chosen = filedialog.asksaveasfilename(
            parent=self, title="Export as",
            defaultextension=".lsdb",
            initialdir=str(self.output_dir() / "exports"),
            filetypes=[("Lyric Sync database", "*.lsdb")])
        if chosen:
            self.export_out_var.set(chosen)

    def _open_output(self) -> None:
        path = self.output_dir()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(path))                    # Windows
        except (AttributeError, OSError):              # pragma: no cover
            messagebox.showinfo("Output folder", str(path), parent=self)

    def _on_close(self) -> None:
        if self.runner.running:
            if not messagebox.askyesno(
                    "Run in progress",
                    "A command is still running. Stop it and quit?",
                    parent=self):
                return
            self.runner.stop()
        self.destroy()


def launch(**kwargs) -> int:                           # pragma: no cover
    """Open the window (called by the ``ui`` CLI command).

    ``tkinter`` is imported at module level, so a Python build without Tk
    fails here and the CLI reports it as an unavailable GUI.
    """
    app = App(**kwargs)
    app.mainloop()
    return 0


__all__ = ["App", "Runner", "launch"]
