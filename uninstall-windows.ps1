# Убирает Punto-переключатель из автозагрузки и останавливает его.
# -Silent - без пауз, для автоматической проверки.

param([switch]$Silent)

$ErrorActionPreference = 'Stop'
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "Punto-переключатель - удаление из автозагрузки" -ForegroundColor White

$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'Punto-переключатель.lnk'
if (Test-Path $lnk) {
    Remove-Item $lnk -Force
    Write-Host "   ярлык автозагрузки удалён" -ForegroundColor Green
} else {
    Write-Host "   ярлыка в автозагрузке не было" -ForegroundColor Yellow
}

$stopper = @'
import ctypes, ctypes.wintypes as w
u = ctypes.WinDLL("user32")
u.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]; u.FindWindowW.restype = w.HWND
h = u.FindWindowW("PuntoPyWnd", None)
if h: u.PostMessageW(h, 0x0010, 0, 0)
print("программа остановлена" if h else "программа не была запущена")
'@
$tmp = Join-Path $env:TEMP 'punto_stop.py'
Set-Content -Path $tmp -Value $stopper -Encoding utf8
if (Get-Command py -ErrorAction SilentlyContinue) {
    Write-Host ("   " + (& py $tmp)) -ForegroundColor Green
}

Write-Host "`nФайлы программы остались на месте - можно запустить install-windows.bat снова." -ForegroundColor White
if (-not $Silent) { Read-Host "Нажмите Enter, чтобы закрыть" | Out-Null }
