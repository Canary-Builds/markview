; Inno Setup Script for VertexMarkdown Windows installer
; Download Inno Setup from: https://jrsoftware.org/isinfo.php
;
; Usage:
;   1. Run build_win.ps1 first to create dist\vertexmarkdown\
;   2. Open this file in Inno Setup Compiler
;   3. Click Build > Compile

#define MyAppName "VertexMarkdown"
#define MyAppVersion "0.6.1"
#define MyAppPublisher "Canary Builds"
#define MyAppURL "https://github.com/Canary-Builds/VertexMarkdown"
#define MyAppExeName "vertexmarkdown.exe"

[Setup]
AppId={{CBDBB5F1-0875-446D-B179-6163A8F02D35}
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
OutputBaseFilename=vertexmarkdown-{#MyAppVersion}-win-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=vertexmarkdown.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associatemd"; Description: "Associate .md files with VertexMarkdown"; GroupDescription: "File associations:"

[Files]
Source: "dist\vertexmarkdown\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Associate .md files
Root: HKCR; Subkey: ".md"; ValueType: string; ValueName: ""; ValueData: "VertexMarkdownFile"; Flags: uninsdeletevalue; Tasks: associatemd
Root: HKCR; Subkey: "VertexMarkdownFile"; ValueType: string; ValueName: ""; ValueData: "Markdown File"; Flags: uninsdeletekey; Tasks: associatemd
Root: HKCR; Subkey: "VertexMarkdownFile\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associatemd
Root: HKCR; Subkey: "VertexMarkdownFile\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatemd

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

