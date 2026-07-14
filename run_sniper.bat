@echo off
rem Carousell Sniper launcher: starts the Discord feed loop + web dashboard,
rem each in its own minimized window with auto-restart (see loop.bat).
rem A copy of this file in shell:startup makes it run at every login.
set SNIPER_DIR=C:\Users\Marvin\low-sale-finder
start "Sniper Feed" /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" feed
start "Sniper Dashboard" /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" dash
