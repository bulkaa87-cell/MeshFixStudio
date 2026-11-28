; Inno Setup script of the Windows installer of MeshFix Studio.
;
;   iscc /DAppVersion=0.4.6 packaging\windows\meshfix_studio.iss
;
; Input: the PyInstaller folder dist\MeshFix Studio\ (see
; packaging\pyinstaller\meshfix_studio.spec). Output:
; dist\MeshFix-Studio-<version>-windows-x64-setup.exe.
;
; The installer asks: for this user only (no administrator rights) or for
; all users. It makes a Start menu entry, and on request a desktop icon and
; the "Open with MeshFix Studio" entry for .stl, .obj and .ply files.

#ifndef AppVersion
  #define AppVersion "0.4.6"
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

; The update from the program (update.py of the program): /RELAUNCH=1
; starts the program again after a silent install. runasoriginaluser: not
; as the administrator of an install for all users.
Filename: "{app}\{#AppExe}"; Check: RelaunchWanted; Flags: nowait runasoriginaluser

[Code]
// An installed version is removed before the new version is installed.
// Without this, files that the new version does not have stay in the
// program folder (an old DLL can then break the program), and an install
// "for all users" and an install "for this user" stay side by side.
// The settings of the program (registry, AppData) stay.

const
  UninstKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E1C7A52-4F0B-4C55-9E7B-2D4F2A6C9B31}_is1';

function OldUninstaller(RootKey: Integer): String;
var
  S: String;
begin
  Result := '';
  if RegQueryStringValue(RootKey, UninstKey, 'UninstallString', S) then
    Result := RemoveQuotes(S);
end;

procedure RemoveOld(RootKey: Integer);
var
  Exe: String;
  Code, Tries: Integer;
begin
  Exe := OldUninstaller(RootKey);
  if (Exe = '') or not FileExists(Exe) then
    Exit;
  Log('Removing the installed version: ' + Exe);
  // ShellExec, not Exec: the uninstaller of an install for all users
  // needs administrator rights, and ShellExec lets Windows ask for them.
  if not ShellExec('', Exe, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
                   '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Log('The uninstaller did not start: ' + SysErrorMessage(Code))
  else
    Log('The uninstaller ended');
  // The uninstaller can delete its own file a moment after it ends: wait
  // for that (at most 15 s), so the new files do not go in too early.
  Tries := 0;
  while FileExists(Exe) and (Tries < 75) do
  begin
    Sleep(200);
    Tries := Tries + 1;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    RemoveOld(HKCU);
    if IsWin64 then
    begin
      RemoveOld(HKLM64);
      RemoveOld(HKLM32);
    end
    else
      RemoveOld(HKLM);
  end;
end;

{ ---- The update from the program (update.py of the program). ----
  The program starts this installer with /SILENT /WAITPID=<its process>
  /RELAUNCH=1 and then closes. The installer waits until that process has
  ended (at most 5 min): only then can the old version go. After the
  install, [Run] starts the program again. }
function OpenProcess(Access: Cardinal; Inherit: Boolean; Pid: Cardinal): Cardinal;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: Cardinal; Ms: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: Cardinal): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function InitializeSetup(): Boolean;
var
  Pid, Handle: Cardinal;
begin
  Result := True;
  Pid := StrToIntDef(ExpandConstant('{param:WAITPID|0}'), 0);
  if Pid = 0 then
    Exit;
  Handle := OpenProcess($00100000 { SYNCHRONIZE }, False, Pid);
  if Handle = 0 then
    Exit;
  Log('Waiting for the program to close (process ' + IntToStr(Pid) + ')');
  WaitForSingleObject(Handle, 300000);
  CloseHandle(Handle);
end;

function RelaunchWanted(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;
