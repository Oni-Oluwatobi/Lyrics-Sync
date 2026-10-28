Lyric Sync — Gospel database location
=====================================

Put the production songbook here as:

    data\lyric_sync_gospel.lsdb

The application opens it READ-ONLY and never modifies it.

Missing-database state? Either place the file above, or launch with:

    set LYRIC_SYNC_DATABASE=C:\path\to\your_songbook.lsdb
    LyricSync.exe

For manual testing without a production database, build the development
fixture (clearly labelled, NOT a real Gospel catalogue):

    python tools\build_dev_fixture.py

then set LYRIC_SYNC_DATABASE to tests\fixtures\lyric_sync_dev_fixture.lsdb
