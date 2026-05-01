; Inno Setup Script for VertexWrite Windows installer
; Download Inno Setup from: https://jrsoftware.org/isinfo.php
;
; Usage:
;   1. Run build_win.ps1 first to create dist\vertexwrite\
;   2. Open this file in Inno Setup Compiler
;   3. Click Build > Compile

#define MyAppName "VertexWrite"
#define MyAppVersion "0.6.6"
#define MyAppPublisher "Canary Builds"
#define MyAppURL "https://github.com/Canary-Builds/vertexwrite"
#define MyAppExeName "vertexwrite.exe"

[Setup]
AppId={{9546AEA2-AA4C-4373-9F09-79348C9C0530}
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
OutputBaseFilename=vertexwrite-{#MyAppVersion}-win-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=vertexwrite.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associatemd"; Description: "Associate .md files with VertexWrite"; GroupDescription: "File associations:"

[Files]
Source: "dist\vertexwrite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Associate .md files
Root: HKCR; Subkey: ".md"; ValueType: string; ValueName: ""; ValueData: "VertexWriteFile"; Flags: uninsdeletevalue; Tasks: associatemd
Root: HKCR; Subkey: "VertexWriteFile"; ValueType: string; ValueName: ""; ValueData: "Markdown File"; Flags: uninsdeletekey; Tasks: associatemd
Root: HKCR; Subkey: "VertexWriteFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associatemd
Root: HKCR; Subkey: "VertexWriteFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatemd

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
