; Inno Setup script for D1CT (Windows).
;
; Builds a per-user installer: the app writes only to %LOCALAPPDATA% and
; needs no driver or service, so requiring an admin prompt would buy
; nothing and would break installing on a locked-down work machine.
;
; Compile after `build.ps1` has produced dist\D1CT\:
;   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\D1CT.iss

#define AppName        "D1CT"
#define AppVersion     "1.5.1"
#define AppPublisher   "metawka"
#define AppURL         "https://github.com/metawka/SuperDictate-win"
#define AppExeName     "D1CT.exe"

[Setup]
AppId={{7B4B2E23-9F3E-4E7B-9E4B-2C1F0C3A5D21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=D1CT-{#AppVersion}-setup
SetupIconFile=..\assets\D1CT.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user: nothing here touches HKLM, Program Files or a service.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The speech model is ~640 MB and is downloaded on first run, so the
; installer itself stays small.
MinVersion=10.0.17763

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStartDescription}"; \
    GroupDescription: "{cm:AutoStartGroup}"

[CustomMessages]
russian.AutoStartGroup=Автозапуск:
russian.AutoStartDescription=Запускать D1CT при входе в Windows
russian.LaunchApp=Запустить D1CT
english.AutoStartGroup=Startup:
english.AutoStartDescription=Start D1CT when I sign in to Windows
english.LaunchApp=Launch D1CT

[Files]
Source: "..\dist\D1CT\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Registry]
; --minimized so an autostarted copy goes straight to the tray instead of
; throwing its control panel at you every login.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "D1CT"; \
    ValueData: """{app}\{#AppExeName}"" --minimized"; \
    Flags: uninsdeletevalue; Tasks: autostart
; The app was called SuperDictate before 1.5.0. Its autostart entry points
; at an executable this installer no longer ships, so it would fail
; silently at every login if it were left in place.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "SuperDictate"; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; The app lives in the tray; a running copy would keep its files locked.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExeName} /F"; \
    Flags: runhidden; RunOnceId: "StopD1CT"

[Code]
// Settings, history and the 640 MB model cache live outside the install
// directory. Leaving them behind by default means a reinstall does not
// re-download the model; the user is asked, so a real uninstall can be
// complete. (Braces are Pascal comments here, and a brace comment cannot
// contain an Inno constant like the app-directory one.)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\D1CT');
    if DirExists(DataDir) then
      if MsgBox('Удалить настройки, историю и загруженную модель распознавания (~640 МБ)?'#13#10 +
                'Remove settings, history and the downloaded speech model (~640 MB)?',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
