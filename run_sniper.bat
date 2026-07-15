@echo off
rem Yujin's Pokestop launcher: Carousell feed + Facebook feed + auction bot +
rem dashboard, each in its own minimized window with auto-restart (loop.bat).
rem A copy of this file in shell:startup makes it run at every login.
set SNIPER_DIR=C:\Users\Marvin\low-sale-finder
start "Pokestop Carousell" /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" feed
start "Pokestop Facebook"  /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" fb
start "Pokestop Bot"       /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" bot
start "Pokestop Dashboard" /min /d "%SNIPER_DIR%" cmd /c "%SNIPER_DIR%\loop.bat" dash
