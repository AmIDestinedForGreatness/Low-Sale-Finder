@echo off
rem Keeps one sniper component alive: restarts it 30s after any crash/exit.
rem Usage: loop.bat feed   (Discord feed loop)
rem        loop.bat dash   (web dashboard)
cd /d "%~dp0"
:top
if "%1"=="feed" (
    E:\python.exe main.py --feed
) else (
    E:\python.exe app.py
)
timeout /t 30 /nobreak >nul
goto top
