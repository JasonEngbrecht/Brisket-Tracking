@echo off
rem Launch the Brisket Tenderness Tracker (script version).
rem Double-click this file to start the app.

rem Run from the folder this .bat lives in, no matter where it's called from.
cd /d "%~dp0"

py -3 "brisket_tenderness.py" %*

rem If Python failed to start, keep the window open so you can read the error.
if errorlevel 1 (
    echo.
    echo The program exited with an error. See the message above.
    pause
)
