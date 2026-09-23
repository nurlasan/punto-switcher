@echo off
rem Remove from startup and stop the program.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall-windows.ps1"
