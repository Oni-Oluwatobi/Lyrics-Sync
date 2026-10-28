; ---------------------------------------------------------------------------
; Lyric Sync - Windows installer (Inno Setup 6)
;
; Build:
;     ISCC.exe LyricSync.iss
;
; Output:  dist\LyricSync-Setup-1.0.0.exe
;
; Per-user install (no UAC): the application is read-only at install time and
; keeps all writable state in %APPDATA%\LyricSync, so no admin rights are
; required. Advanced users can still force an all-users install with /ALLUSERS.
; ---------------------------------------------------------------------------

#define MyAppName "Lyric Sync"
#define MyAppId "{{AC88197D-A5EA-4278-89A7-A3DFAC7D904B}"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "The Kreadive Galaxy"
#define MyAppURL "https://the-kreadive-galaxy.web.app/"
#define MyAppExeName "LyricSync.exe"
#define MySourceDir "dist\LyricSync"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\LyricSync
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=LyricSync-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductTextVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
DisableWelcomePage=no
DisableReadyPage=no
ChangesAssociations=no
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Offline Gospel song identification from remembered lyrics"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Application state lives in %APPDATA%\LyricSync and is intentionally kept
; after uninstall (favorites and search history are user data).
Type: files; Name: "{app}\*.log"
