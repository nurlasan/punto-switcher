@echo off
rem Запуск без окна консоли. Ярлык на этот файл можно положить в автозагрузку:
rem   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
where pyw >nul 2>&1 && (start "" pyw "%~dp0punto.py" %*) || (start "" pythonw "%~dp0punto.py" %*)
