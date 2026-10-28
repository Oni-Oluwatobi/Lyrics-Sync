"""About page: version, database statistics, credits and links."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from lyric_sync import APP_NAME, DEVELOPER, VERSION
from lyric_sync.app.theme import SP_LG, SP_MD, SP_SM, SP_XL
from lyric_sync.ui.components.widgets import CenterColumn, Chip, MetricCard, SectionTitle

WEBSITE_URL = "https://the-kreadive-galaxy.web.app/"


class AboutPage(QWidget):
    """Version, real database statistics, tagline and credits."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        container = CenterColumn(max_width=800)
        self._container = container
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 20, 0, 48)
        column.setSpacing(0)

        heading = QLabel("About")
        heading.setProperty("role", "pageTitle")
        column.addWidget(heading)
        column.addSpacing(SP_XL)

        # -------------------------------------------------------- identity
        card, layout = self._card()
        title = QLabel(APP_NAME)
        title.setProperty("role", "display")
        layout.addWidget(title)

        tagline = QLabel("Find the song. Sing the truth.")
        tagline.setProperty("role", "accent")
        layout.addWidget(tagline)
        layout.addSpacing(SP_SM)

        body = QLabel(
            "Offline Gospel song identification from remembered lyrics. "
            "Type the line you remember and Lyric Sync searches the local "
            "songbook on this computer — instantly, with no internet "
            "required for searching."
        )
        body.setProperty("role", "body")
        body.setWordWrap(True)
        layout.addWidget(body)

        version_row = QHBoxLayout()
        version_row.setSpacing(SP_SM)
        version_row.addWidget(Chip(f"VERSION {VERSION}", "meta"))
        version_row.addWidget(Chip(f"BY {DEVELOPER.upper()}", "meta"))
        version_row.addStretch(1)
        layout.addLayout(version_row)
        column.addWidget(card)
        column.addSpacing(SP_LG)

        # ----------------------------------------------------- statistics
        stats_card, stats_layout = self._card()
        stats_layout.addWidget(SectionTitle("Local database"))
        stats_layout.addSpacing(SP_MD)

        metrics = QHBoxLayout()
        metrics.setSpacing(SP_MD)
        self.songs_metric = MetricCard("SONG", "—")
        self.lines_metric = MetricCard("LYRIC LINE", "—")
        self.size_metric = MetricCard("SIZE", "—")
        metrics.addWidget(self.songs_metric)
        metrics.addWidget(self.lines_metric)
        metrics.addWidget(self.size_metric)
        stats_layout.addLayout(metrics)

        self.database_note = QLabel("Waiting for the database…")
        self.database_note.setProperty("role", "caption")
        self.database_note.setWordWrap(True)
        stats_layout.addWidget(self.database_note)
        column.addWidget(stats_card)
        column.addSpacing(SP_LG)

        # ---------------------------------------------------- application
        app_card, app_layout = self._card()
        app_layout.addWidget(SectionTitle("Application"))
        app_layout.addSpacing(SP_MD)

        for key, value in (
            ("Version", VERSION),
            ("Developer", DEVELOPER),
            ("Website", WEBSITE_URL),
            ("User data", "Preferences, favorites and account session are stored "
                          "locally on this device."),
        ):
            row = QHBoxLayout()
            row.setSpacing(SP_MD)
            key_label = QLabel(key)
            key_label.setProperty("role", "metaKey")
            key_label.setMinimumWidth(90)
            row.addWidget(key_label)
            value_label = QLabel(value)
            value_label.setProperty("role", "metaValue")
            value_label.setWordWrap(True)
            row.addWidget(value_label, 1)
            app_layout.addLayout(row)
        column.addWidget(app_card)
        column.addSpacing(SP_LG)

        # -------------------------------------------------------- privacy
        privacy_card, privacy_layout = self._card()
        privacy_card.setObjectName("panelFlat")
        privacy_layout.addWidget(SectionTitle("Privacy"))
        privacy_layout.addSpacing(SP_MD)
        privacy = QLabel(
            "•  Searching, favorites and settings run fully offline.\n"
            "•  Signing in is optional. When used, the account calls Google "
            "Firebase Identity Toolkit over HTTPS — the song database and your "
            "queries are never uploaded.\n"
            "•  No analytics, no telemetry, no update checks."
        )
        privacy.setProperty("role", "body")
        privacy.setWordWrap(True)
        privacy_layout.addWidget(privacy)
        column.addWidget(privacy_card)
        column.addSpacing(SP_LG)

        # --------------------------------------------------------- credits
        credits_card, credits_layout = self._card()
        credits_layout.addWidget(SectionTitle("Credits"))
        credits_layout.addSpacing(SP_MD)
        credits = QLabel(
            f"•  {APP_NAME} is a product of {DEVELOPER}.\n"
            "•  The Gospel songbook is built from authorized public-domain "
            "hymn sources — full provenance lives in Settings → Database → "
            "Database Information.\n"
            "•  Brand colours: orange · yellow · white · deep charcoal."
        )
        credits.setProperty("role", "body")
        credits.setWordWrap(True)
        credits_layout.addWidget(credits)
        column.addWidget(credits_card)

        outer.addWidget(container, 1)
        outer.addStretch(1)

    # --------------------------------------------------------------- layout

    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SP_XL, SP_LG, SP_XL, SP_LG)
        layout.setSpacing(0)
        return card, layout

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._container.sync_width(self.width())

    # ------------------------------------------------------------------ api

    def set_stats(
        self,
        song_count: int | None,
        line_count: int | None,
        size_label: str = "",
        database_name: str = "",
        database_version: str = "",
    ) -> None:
        """Real figures from the loaded database — never invented."""
        if song_count is None:
            self.songs_metric.set_metric("—", "SONG")
            self.lines_metric.set_metric("—", "LYRIC LINE")
            self.size_metric.set_metric("—", "SIZE")
            self.database_note.setText(
                "The local Gospel database is not installed yet."
            )
            return
        self.songs_metric.set_metric(f"{song_count:,}", "SONG")
        if line_count is not None:
            self.lines_metric.set_metric(f"{line_count:,}", "LYRIC LINE")
        else:
            self.lines_metric.set_metric("—", "LYRIC LINE")
        self.size_metric.set_metric(size_label or "—", "SIZE")
        parts = [part for part in (database_name, database_version) if part]
        joined = "  ·  ".join(parts)
        self.database_note.setText(
            (joined + "  ·  searching is fully offline." if joined
             else "Searching is fully offline.")
        )
