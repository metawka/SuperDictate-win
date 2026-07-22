; Inno Setup script for Dictation (Windows).
;
; Builds a per-user installer: the app writes only to %LOCALAPPDATA% and
; needs no driver or service, so requiring an admin prompt would buy
; nothing and would break installing on a locked-down work machine.
;
; Compile after `build.ps1` has produced dist\Dictation\:
;   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\Dictation.iss

#define AppName        "Dictation"
#define AppVersion     "2.2.2"
#define AppPublisher   "metawka"
#define AppURL         "https://github.com/metawka/SuperDictate-win"
#define AppExeName     "Dictation.exe"
; Must match superdictate.system.APP_USER_MODEL_ID, or the taskbar treats a
; pinned shortcut and the running window as two different applications.
#define AppUserModelID "metawka.Dictation"

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
OutputBaseFilename=Dictation-{#AppVersion}-setup
SetupIconFile=..\assets\Dictation.ico
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
russian.AutoStartDescription=Запускать Dictation при входе в Windows
russian.LaunchApp=Запустить Dictation
english.AutoStartGroup=Startup:
english.AutoStartDescription=Start Dictation when I sign in to Windows
english.LaunchApp=Launch Dictation

[Files]
Source: "..\dist\Dictation\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; The executable and the shortcuts were named D1CT until 1.8.0. Upgrading
; in place would otherwise leave a second, stale copy of the app behind
; and two entries in the Start menu.
Type: files; Name: "{app}\D1CT.exe"
Type: files; Name: "{group}\D1CT.lnk"
Type: files; Name: "{autodesktop}\D1CT.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; --minimized so an autostarted copy goes straight to the tray instead of
; throwing its control panel at you every login.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#AppName}"; \
    ValueData: """{app}\{#AppExeName}"" --minimized"; \
    Flags: uninsdeletevalue; Tasks: autostart
; The app was called D1CT before 1.8.0 and SuperDictate before 1.5.0. Those
; autostart entries point at executables this installer no longer ships, so
; they would fail silently at every login if left in place.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "D1CT"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "SuperDictate"; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; The app lives in the tray; a running copy would keep its files locked.
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExeName} /F"; \
    Flags: runhidden; RunOnceId: "StopDictation"

[Code]
const
  SHCNE_ASSOCCHANGED = $08000000;
  SHCNF_IDLIST       = $0000;

procedure SHChangeNotify(EventId: LongInt; Flags: Cardinal;
                         Item1, Item2: LongInt);
  external 'SHChangeNotify@shell32.dll stdcall';

// Explorer caches the icon it has seen for an executable, so after the
// artwork changed the taskbar and the Start menu kept drawing the old one
// until something told the shell to look again.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0);
end;

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
    DataDir := ExpandConstant('{localappdata}\Dictation');
    if DirExists(DataDir) then
      if MsgBox('Удалить настройки, историю и загруженную модель распознавания (~640 МБ)?'#13#10 +
                'Remove settings, history and the downloaded speech model (~640 MB)?',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
