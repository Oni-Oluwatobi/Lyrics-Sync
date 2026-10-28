@echo off
rem Gospel lyrics database builder (OpenGospelLyrics + African Gospel Lyrics).
rem Usage: lyrics-scraper <command> [options]   (see: lyrics-scraper --help)
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
python -m lyrics_scraper %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
