# Установка Punto-переключателя: автозагрузка + запуск.
# Запускается из install-windows.bat, отдельно вызывать не нужно.
# -Silent - без пауз, для автоматической проверки.

param([switch]$Silent)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Шаг($text) { Write-Host "`n>> $text" -ForegroundColor Cyan }
function Готово($text) { Write-Host "   $text" -ForegroundColor Green }
function Плохо($text) { Write-Host "   $text" -ForegroundColor Red }
function Пауза($text) { if (-not $Silent) { Read-Host $text | Out-Null } }

Write-Host "Punto-переключатель - установка" -ForegroundColor White

# --- 1. Python -------------------------------------------------------------
Шаг "Проверяю Python"
$python = $null
foreach ($cmd in @('pyw', 'pythonw')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source; break }
}
if (-not $python) {
    Плохо "Python не найден."
    Write-Host "   Установите его с https://www.python.org/downloads/ (галочку" -ForegroundColor Yellow
    Write-Host "   'Add Python to PATH' при установке оставьте включённой) и запустите меня снова." -ForegroundColor Yellow
    if (-not $Silent) {
        Пауза "Нажмите Enter, чтобы открыть страницу загрузки"
        Start-Process "https://www.python.org/downloads/"
    }
    exit 1
}
Готово "нашёл: $python"

# --- 2. Файлы программы ----------------------------------------------------
Шаг "Проверяю файлы программы"
$missing = @()
foreach ($file in @('punto.py', 'core.py', 'layouts.py', 'spell.py', 'wordset.py',
                    'dict_ru.txt', 'dict_en.txt', 'model.json')) {
    if (-not (Test-Path (Join-Path $here $file))) { $missing += $file }
}
if ($missing.Count -gt 0) {
    Плохо ("не хватает файлов: " + ($missing -join ', '))
    Пауза "Нажмите Enter"
    exit 1
}
Готово "все на месте"

# --- 3. Самопроверка -------------------------------------------------------
Шаг "Проверяю, что словари и логика работают"
$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) {
    $env:PYTHONIOENCODING = 'utf-8'
    $result = & py (Join-Path $here 'tests.py') 2>&1
    if ($LASTEXITCODE -eq 0) {
        Готово "тесты пройдены"
    } else {
        Плохо "тесты не прошли:"
        $result | Select-Object -Last 10 | ForEach-Object { Write-Host "     $_" }
        Пауза "Нажмите Enter"
        exit 1
    }
} else {
    Готово "пропускаю (нет команды py)"
}

# --- 4. Остановить старую копию -------------------------------------------
Шаг "Останавливаю прежнюю копию, если запущена"
$stopper = @'
import ctypes, ctypes.wintypes as w
u = ctypes.WinDLL("user32")
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]; u.FindWindowW.restype = w.HWND
h = u.FindWindowW("PuntoPyWnd", None)
if h: u.PostMessageW(h, 0x0010, 0, 0)
print("остановлена" if h else "не была запущена")
'@
$tmp = Join-Path $env:TEMP 'punto_stop.py'
Set-Content -Path $tmp -Value $stopper -Encoding utf8
if ($py) { Готово (& py $tmp) } else { Готово "пропускаю" }
Start-Sleep -Milliseconds 700

# --- 5. Автозагрузка -------------------------------------------------------
Шаг "Добавляю в автозагрузку"
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'Punto-переключатель.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + (Join-Path $here 'punto.py') + '" --auto --spell'
$shortcut.WorkingDirectory = $here
$shortcut.Description = 'Переключатель раскладки и орфографии'
$shortcut.Save()
Готово "ярлык: $lnk"

# --- 6. Запуск -------------------------------------------------------------
Шаг "Запускаю"
Start-Process -FilePath $python -ArgumentList @(('"' + (Join-Path $here 'punto.py') + '"'), '--auto', '--spell') -WorkingDirectory $here
Start-Sleep -Seconds 3
if ($py) {
    $checker = @'
import ctypes, ctypes.wintypes as w
u = ctypes.WinDLL("user32")
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]; u.FindWindowW.restype = w.HWND
print("работает" if u.FindWindowW("PuntoPyWnd", None) else "НЕ ЗАПУСТИЛАСЬ")
'@
    $tmp2 = Join-Path $env:TEMP 'punto_check.py'
    Set-Content -Path $tmp2 -Value $checker -Encoding utf8
    Готово (& py $tmp2)
}

Write-Host "`nГотово. Программа висит иконкой в трее (у часов)." -ForegroundColor White
Write-Host @"

   Pause             - перевести последнее слово в другую раскладку
   Shift+Pause       - перевести выделенный текст
   Ctrl+Alt+Pause    - исправить опечатку в слове
   Ctrl+Pause        - включить/выключить авто-раскладку
   Ctrl+Shift+Pause  - выход

   Авто-раскладка и авто-орфография уже включены.
   Убрать из автозагрузки: uninstall-windows.bat
"@
Пауза "Нажмите Enter, чтобы закрыть"
