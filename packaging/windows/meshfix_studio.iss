; Inno Setup script of the Windows installer of MeshFix Studio.
;
;   iscc /DAppVersion=0.3.1 packaging\windows\meshfix_studio.iss
;
; Input: the PyInstaller folder dist\MeshFix Studio\ (see
; packaging\pyinstaller\meshfix_studio.spec). Output:
; dist\MeshFix-Studio-<version>-windows-x64-setup.exe.
;
; The installer asks: for this user only (no administrator rights) or for
; all users. It makes a Start menu entry, and on request a desktop icon and
; the "Open with MeshFix Studio" entry for .stl, .obj and .ply files.

#ifndef AppVersion
  #define AppVersion "0.3.1"
#endif
#define AppName "MeshFix Studio"
#define AppExe "MeshFix Studio.exe"
#define SrcDir "..\..\dist\MeshFix Studio"

[Setup]
AppId={{6E1C7A52-4F0B-4C55-9E7B-2D4F2A6C9B31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MeshFix Studio contributors
AppPublisherURL=https://github.com/bulkaa87-cell/MeshFixStudio
AppSupportURL=https://github.com/bulkaa87-cell/MeshFixStudio/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=MeshFix-Studio-{#AppVersion}-windows-x64-setup
SetupIconFile=..\icons\meshfix-studio.ico
; The pictures of the wizard (packaging/icons/make_icons.py): 100 % and 200 %.
WizardImageFile=..\icons\wizard-large-100.bmp,..\icons\wizard-large-200.bmp
WizardSmallImageFile=..\icons\wizard-small-100.bmp,..\icons\wizard-small-200.bmp
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
WizardStyle=modern

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assoc"; Description: "Open .stl, .obj and .ply files with {#AppName}"; GroupDescription: "Files:"; Flags: unchecked

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Open with" entries. They do not take the default program of a type away
; from another program: Windows asks the person.
Root: HKA; Subkey: "Software\Classes\MeshFixStudio.Mesh"; ValueType: string; ValueName: ""; ValueData: "Triangle mesh"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\MeshFixStudio.Mesh\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\MeshFixStudio.Mesh\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.stl\OpenWithProgids"; ValueType: string; ValueName: "MeshFixStudio.Mesh"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.obj\OpenWithProgids"; ValueType: string; ValueName: "MeshFixStudio.Mesh"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.ply\OpenWithProgids"; ValueType: string; ValueName: "MeshFixStudio.Mesh"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
