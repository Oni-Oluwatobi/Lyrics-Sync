"""Developer-facing database information: telemetry cards + build manifest."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL
from lyric_sync.database.database_validator import ValidationReport
from lyric_sync.database.lsdb_manager import DatabaseInfo
from lyric_sync.ui.components.widgets import (
    BackButton,
    CenterColumn,
    Chip,
    GlyphLabel,
    MetricCard,
    SectionTitle,
)


def read_provenance(path: str | Path) -> tuple[str, list[tuple]]:
    """SHA-256 digest + build-manifest rows, read-only, off the UI thread.

    Opens its own ``file:…?mode=ro`` connection — ``LSDBManager`` and its
    ``PRAGMA query_only`` session are never touched.  Used by the database
    info page only.
    """
    import hashlib

    file_path = Path(path)
    digest = ""
    if file_path.is_file():
        hasher = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()

    manifest: list[tuple] = []
    if file_path.is_file():
        try:
            con = sqlite3.connect(f"file:{file_path}?mode=ro", uri=True)
            try:
                con.execute("PRAGMA query_only = ON")
                rows = con.execute(
                    "SELECT title, author, published, ebook_id, license, "
                    "songs_accepted FROM build_manifest ORDER BY source_key"
                ).fetchall()
                manifest.extend(rows)
            finally:
                con.close()
        except sqlite3.Error:
            pass
    return digest, manifest


class DatabaseInfoPage(QWidget):
    """Statistics and validation results for the loaded ``.LSDB``."""

    back_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manifest: list[tuple] = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_host = QWidget()
        scroll_layout = QHBoxLayout(scroll_host)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.addStretch(1)

        container = CenterColumn(max_width=1000)
        self._container = container
        scroll_layout.addWidget(container)
        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_host)
        outer.addWidget(scroll, 1)

        column = QVBoxLayout(container)
        column.setContentsMargins(0, SP_XL, 0, SP_XL)
        column.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(SP_MD)
        back = BackButton("Settings")
        back.clicked.connect(self.back_requested)
        header.addWidget(back)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setProperty("variant", "secondary")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh_requested)
        header.addWidget(refresh)
        column.addLayout(header)

        column.addSpacing(SP_LG)

        title_row = QHBoxLayout()
        title_row.setSpacing(SP_MD)
        icon = GlyphLabel("database", size=22, color="accent")
        title_row.addWidget(icon)
        title = QLabel("Database information")
        title.setProperty("role", "pageTitle")
        title_row.addWidget(title, 1)
        self.status_chip = Chip("", "meta")
        title_row.addWidget(self.status_chip)
        column.addLayout(title_row)

        subtitle = QLabel("Developer view of the local Gospel song database (.LSDB).")
        subtitle.setProperty("role", "muted")
        column.addWidget(subtitle)
        column.addSpacing(SP_XL)

        # ---- telemetry metric cards
        metrics = QHBoxLayout()
        metrics.setSpacing(SP_MD)
        self.metric_file = MetricCard("Songbook file", "—")
        self.metric_digest = MetricCard("Content digest SHA-256", "—")
        self.metric_counts = MetricCard("Songs · lyric lines", "—")
        self.metric_fts = MetricCard("FTS engine", "—")
        for card in (self.metric_file, self.metric_digest,
                     self.metric_counts, self.metric_fts):
            metrics.addWidget(card, 1)
        column.addLayout(metrics)
        column.addSpacing(SP_LG)

        # ---- detail tree
        column.addWidget(SectionTitle("Details"))
        column.addSpacing(SP_SM)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setMinimumHeight(220)
        column.addWidget(self.tree, 1)
        column.addSpacing(SP_LG)

        # ---- provenance / build manifest table
        self.manifest_title = SectionTitle("Build manifest")
        column.addWidget(self.manifest_title)
        column.addSpacing(SP_SM)
        self.manifest_table = QTreeWidget()
        self.manifest_table.setColumnCount(5)
        self.manifest_table.setHeaderLabels(
            ["Source", "Published", "eBook", "Songs", "License"]
        )
        self.manifest_table.setAlternatingRowColors(True)
        self.manifest_table.setRootIsDecorated(False)
        self.manifest_table.header().setStretchLastSection(True)
        self.manifest_table.header().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.manifest_table.header().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.manifest_table.header().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.manifest_table.header().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.manifest_table.setMinimumHeight(180)
        column.addWidget(self.manifest_table, 1)

        column.addSpacing(SP_LG)

        actions = QHBoxLayout()
        actions.setSpacing(SP_SM)
        copy = QPushButton("Copy report")
        copy.setProperty("variant", "secondary")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy_report)
        actions.addWidget(copy)
        self.message = QLabel("")
        self.message.setProperty("role", "caption")
        actions.addWidget(self.message, 1)
        column.addLayout(actions)

        self._report_text = ""

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._container.sync_width(self.width())

    # ------------------------------------------------------------------ api

    def show_loading(self) -> None:
        self.status_chip.setText("READING…")
        self.status_chip.set_kind("meta")
        self.tree.clear()
        QTreeWidgetItem(self.tree, ["Status", "Reading database…"])
        self.manifest_table.clear()
        self.metric_file.set_metric("—", "Songbook file")
        self.metric_digest.set_metric("—", "Content digest SHA-256")
        self.metric_counts.set_metric("—", "Songs · lyric lines")
        self.metric_fts.set_metric("—", "FTS engine")
        self._report_text = ""

    def show_missing(self, expected_path: str) -> None:
        self.status_chip.setText("MISSING")
        self.status_chip.set_kind("warn")
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, ["Database", ""])
        QTreeWidgetItem(root, ["Status", "Not installed"])
        QTreeWidgetItem(root, ["Expected", expected_path])
        root.setExpanded(True)
        self.manifest_table.clear()
        self.metric_file.set_metric(expected_path, "Expected location")
        self.metric_digest.set_metric("—", "Content digest SHA-256")
        self.metric_counts.set_metric("—", "Songs · lyric lines")
        self.metric_fts.set_metric("—", "FTS engine")
        self._report_text = f"Database not installed. Expected: {expected_path}"

    def set_extra(self, digest: str, manifest: list[tuple]) -> None:
        """SHA-256 + build-manifest rows gathered by the background worker."""
        self._manifest = list(manifest)
        self.metric_digest.set_metric(
            (digest[:16] + "…") if digest else "—", "Content digest SHA-256"
        )
        self.metric_digest.value_label.setToolTip(digest or "")
        self.manifest_table.clear()
        for title, author, published, ebook_id, license_text, accepted in manifest:
            item = QTreeWidgetItem(
                self.manifest_table,
                [
                    f"{title} — {author}",
                    str(published or "—"),
                    f"#{ebook_id}" if ebook_id else "—",
                    f"{accepted:,}",
                    license_text or "—",
                ],
            )
            item.setToolTip(0, title)
            item.setToolTip(4, license_text or "")
        self.manifest_title.setVisible(True)
        self.manifest_table.setVisible(bool(manifest))

    def set_info(self, info: DatabaseInfo, report: ValidationReport | None = None) -> None:
        self.status_chip.setText("LOADED")
        self.status_chip.set_kind("verified")

        self.metric_file.set_metric(info.filename, "Songbook file")
        self.metric_file.setToolTip(info.path)
        self.metric_counts.set_metric(
            f"{info.song_count:,} · {info.lyric_line_count:,}",
            "Songs · lyric lines",
        )
        if info.fts_available:
            self.metric_fts.set_metric("FTS5 Active", "Search index")
        else:
            self.metric_fts.set_metric("Not available", "Search index")

        self.tree.clear()

        def group(title: str, rows: list[tuple[str, str]]) -> QTreeWidgetItem:
            node = QTreeWidgetItem(self.tree, [title, ""])
            for key, value in rows:
                QTreeWidgetItem(node, [key, value])
            node.setExpanded(True)
            return node

        group(
            "File",
            [
                ("Filename", info.filename),
                ("Location", info.path),
                ("Size", info.size_label),
                ("Tables", str(info.table_count)),
            ],
        )
        group(
            "Versions",
            [
                ("Database version", info.version or "not recorded"),
                ("Schema version", info.schema_version or "not recorded"),
                ("Generated by", info.generated_by or "not recorded"),
            ],
        )
        group(
            "Contents",
            [
                ("Songs", f"{info.song_count:,}"),
                ("Artists", f"{info.artist_count:,}"),
                ("Lyric lines", f"{info.lyric_line_count:,}"),
                ("Lyric sections", f"{info.lyric_section_count:,}"),
                ("Aliases", f"{info.alias_count:,}"),
                ("Songs table", info.songs_table or "—"),
                ("Lyric lines table", info.lyric_lines_table or "—"),
            ],
        )
        group(
            "Search index",
            [
                ("FTS availability", "Available" if info.fts_available else "Not available"),
                ("FTS tables", ", ".join(info.fts_tables) or "—"),
                ("Indexed rows", f"{info.fts_indexed_rows:,}"),
            ],
        )
        group(
            "Verification",
            [
                (key, f"{value:,}")
                for key, value in sorted(info.verification_stats.items())
            ] or [("Records", "none recorded")],
        )
        group(
            "Copyright status",
            [
                (key, f"{value:,}")
                for key, value in sorted(info.copyright_stats.items())
            ] or [("Records", "none recorded")],
        )
        group(
            "Integrity",
            [
                ("Status", info.integrity_status),
                ("Detail", info.integrity_detail or "—"),
            ],
        )
        if info.notes:
            group("Notes", [(f"Note {index + 1}", note) for index, note in enumerate(info.notes)])

        if report is not None:
            node = QTreeWidgetItem(self.tree, ["Validation", report.summary])
            for check in report.checks:
                QTreeWidgetItem(node, [check.name, f"[{check.status}] {check.detail}"])
            node.setExpanded(True)
            self._report_text = report.to_text()
        else:
            self._report_text = (
                f"Lyric Sync database information\n"
                f"File: {info.filename}\nPath: {info.path}\nSize: {info.size_label}\n"
                f"Songs: {info.song_count}\nLyric lines: {info.lyric_line_count}\n"
                f"FTS: {'yes' if info.fts_available else 'no'}\n"
                f"Integrity: {info.integrity_status}"
            )
        self.message.setText("")

    # ------------------------------------------------------------ internals

    def _copy_report(self) -> None:
        if not self._report_text:
            QMessageBox.information(self, "Copy report", "There is nothing to copy yet.")
            return
        QApplication.clipboard().setText(self._report_text)
        self.message.setText("Report copied to the clipboard.")
