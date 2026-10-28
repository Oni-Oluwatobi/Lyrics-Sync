@echo off
rem Gospel lyrics database builder (OpenGospelLyrics + African Gospel Lyrics).
rem Works from any folder:  lyrics-scraper [command] [options]
rem No command opens the desktop interface; see lyrics-scraper --help
setlocal
set "PYTHONPATH=%~dp0tools\lyrics-scraper;%PYTHONPATH%"
python -m lyrics_scraper %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
