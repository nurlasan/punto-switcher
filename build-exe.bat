@echo off
rem Сборка dist\Tilashar.exe и установщика dist\Tilashar-Setup.exe.
rem Нужны Python + PyInstaller (py -m pip install pyinstaller) и Inno Setup 6.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
py tests.py || (echo Тесты не прошли, сборку не начинаю. & exit /b 1)
py -m PyInstaller --noconfirm tilashar.spec || exit /b 1

for /f "delims=" %%v in ('py -c "from version import VERSION; print(VERSION)"') do set VER=%%v
set ISCC=
for %%p in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%p set ISCC=%%p
if not defined ISCC (
    echo Inno Setup 6 не найден - собран только dist\Tilashar.exe.
    exit /b 0
)
%ISCC% /Q /DAppVersion=%VER% installer\tilashar.iss || exit /b 1
echo.
echo Готово: dist\Tilashar.exe и dist\Tilashar-Setup.exe (версия %VER%)
