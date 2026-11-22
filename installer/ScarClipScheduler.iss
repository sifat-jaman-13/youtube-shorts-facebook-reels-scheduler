#define AppName "ScarClipScheduler"
#define AppVersion "2.0.4"
#define AppPublisher "Sifat Jaman / ScarZero"
#define AppExeName "ScarClipScheduler.exe"

[Setup]
AppId={{6A8E9A80-24A1-45D3-9D5E-11A5F2D1C2A7}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\ScarClipScheduler
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=ScarClipScheduler-Setup
SetupIconFile=..\assets\scarclipscheduler.ico
UninstallDisplayIcon={app}\ScarClipScheduler.exe
VersionInfoVersion=2.0.4.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=ScarClipScheduler Windows installer
VersionInfoProductName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\package\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ScarClipScheduler"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall ScarClipScheduler"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ScarClipScheduler"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Install-ScarClipScheduler.ps1"""; WorkingDir: "{app}"; Description: "Check prerequisites and prepare the publishing worker"; StatusMsg: "Checking Python and installing any missing publishing requirements..."; Flags: waituntilterminated

[Code]
function SchedulerIsRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{sys}\cmd.exe'),
    '/C tasklist /FI "IMAGENAME eq ScarClipScheduler.exe" /FO CSV /NH | find /I "ScarClipScheduler.exe" >NUL',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := (ResultCode = 0);
  end;
end;

function InitializeSetup(): Boolean;
begin
  if SchedulerIsRunning() then
  begin
    MsgBox('ScarClipScheduler is currently running.' + #13#10 + #13#10 +
      'Click Quit in ScarClipScheduler, allow any active upload to finish, and then run this installer again.'
      + #13#10 + #13#10 + 'The installer will not close the application or interrupt your publishing queue.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  if SchedulerIsRunning() then
  begin
    MsgBox('ScarClipScheduler is currently running. Click Quit before uninstalling it.',
      mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;

