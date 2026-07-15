@echo off
rem Keeps one sniper component alive: restarts it 30s after any crash/exit.
rem Usage: loop.bat feed   (Carousell Discord feed loop)
rem        loop.bat fb     (Facebook groups feed loop)
rem        loop.bat bot    (Discord bot: react-to-track auctions)
rem        loop.bat dash   (web dashboard)
cd /d "%~dp0"
:top
if "%1"=="feed" (
    E:\python.exe main.py --feed
) else if "%1"=="fb" (
    E:\python.exe fb_feed.py
) else if "%1"=="bot" (
    E:\python.exe bot.py
) else (
    E:\python.exe app.py
)
timeout /t 30 /nobreak >nul
goto top
