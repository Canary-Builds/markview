; Inno Setup Script for markview Windows installer
; Download Inno Setup from: https://jrsoftware.org/isinfo.php
;
; Usage:
;   1. Run build_win.bat first to create dist\markview\
;   2. Open this file in Inno Setup Compiler
;   3. Click Build > Compile

#define MyAppName "markview"
#define MyAppVersion "0.5.4"
#define MyAppPublisher "Canary Builds"
#define MyAppURL "https://github.com/Canary-Builds/markview"
#define MyAppExeName "markview.exe"

[Setup]
AppId={{B4A7C8D2-3E5F-4A6B-9C1D-8E2F7A3B5C4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppCopyright=Copyright (c) 2026 Canary Builds
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.windows.txt
OutputDir=installer_output
OutputBaseFilename=markview-{#MyAppVersion}-win-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=markview.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associatemd"; Description: "Associate .md files with markview"; GroupDescription: "File associations:"

[Files]
Source: "dist\markview\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Associate .md files
Root: HKCR; Subkey: ".md"; ValueType: string; ValueName: ""; ValueData: "MarkviewFile"; Flags: uninsdeletevalue; Tasks: associatemd
Root: HKCR; Subkey: "MarkviewFile"; ValueType: string; ValueName: ""; ValueData: "Markdown File"; Flags: uninsdeletekey; Tasks: associatemd
Root: HKCR; Subkey: "MarkviewFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associatemd
Root: HKCR; Subkey: "MarkviewFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatemd

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
