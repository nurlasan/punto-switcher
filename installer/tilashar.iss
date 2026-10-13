; Установщик Tilashar (Inno Setup 6).
; Собирается build-exe.bat или вручную:
;   ISCC.exe /DAppVersion=1.0.0 installer\tilashar.iss
; Берёт готовый dist\Tilashar.exe, кладёт dist\Tilashar-Setup.exe.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1C2B7E-4A0D-4E8B-9C51-7A3E2D9B1F40}
AppName=Tilashar
AppVersion={#AppVersion}
AppVerName=Tilashar {#AppVersion}
AppPublisher=Tilashar
AppPublisherURL=https://github.com/nurlasan/punto-switcher
; без прав администратора: в папку пользователя, куда exe сможет писать при обновлении
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Tilashar
DisableProgramGroupPage=yes
DisableDirPage=auto
InfoBeforeFile=about.txt
OutputDir=..\dist
OutputBaseFilename=Tilashar-Setup
SetupIconFile=..\tilashar.ico
UninstallDisplayIcon={app}\Tilashar.exe
UninstallDisplayName=Tilashar
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "autostart"; Description: "Запускать Tilashar при входе в Windows"; GroupDescription: "Дополнительно:"
Name: "desktopicon"; Description: "Значок на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "..\dist\Tilashar.exe"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; автозагрузка скриптовой версии (install-windows.bat) - иначе стартуют обе
Type: files; Name: "{userstartup}\Punto-переключатель.lnk"

[Icons]
Name: "{autoprograms}\Tilashar"; Filename: "{app}\Tilashar.exe"
Name: "{autodesktop}\Tilashar"; Filename: "{app}\Tilashar.exe"; Tasks: desktopicon

[Registry]
; то же значение переключает пункт меню «Запускать вместе с Windows»
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "Tilashar"; ValueData: """{app}\Tilashar.exe"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Tilashar.exe"; Description: "Запустить Tilashar"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Tilashar.exe /F"; Flags: runhidden; RunOnceId: "StopTilashar"

[Code]
const
  WM_CLOSE = $0010;

{ Закрыть работающую копию (окно класса PuntoPyWnd), иначе exe не перезаписать }
procedure CloseRunning();
var
  Wnd: HWND;
  I: Integer;
begin
  Wnd := FindWindowByClassName('PuntoPyWnd');
  if Wnd = 0 then
    Exit;
  PostMessage(Wnd, WM_CLOSE, 0, 0);
  for I := 1 to 50 do
  begin
    Sleep(100);
    if FindWindowByClassName('PuntoPyWnd') = 0 then
      Break;
  end;
  Sleep(500);   { даём процессу выйти и отпустить файл }
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunning();
  Result := '';
end;

{ Если галочку автозапуска сняли при переустановке - убрать старое значение }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardIsTaskSelected('autostart') then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Tilashar');
end;
