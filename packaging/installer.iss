#define MyAppName "FastVideoAssembly"
#include "..\build\downloads.iss"

[Setup]
AppId=electblake.FastVideoAssembly
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installer
OutputBaseFilename=FastVideoAssembly-{#MyAppVersion}-windows-amd64-Setup
UninstallDisplayIcon={app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico
SetupIconFile=..\src\fastvideoassembly\icons\violet.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchiveExtraction=full
LicenseFile=..\LICENSE
InfoBeforeFile=online-install.txt
SetupLogging=yes

[Files]
Source: "..\LICENSE"; DestDir: "{app}\application"; Flags: ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}\application"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}\application"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}\application"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}\application"; Flags: ignoreversion
Source: "..\src\fastvideoassembly\*.py"; DestDir: "{app}\application\src\fastvideoassembly"; Flags: ignoreversion
Source: "..\src\fastvideoassembly\*.ico"; DestDir: "{app}\application\src\fastvideoassembly"; Flags: ignoreversion
Source: "..\src\fastvideoassembly\icons\*.ico"; DestDir: "{app}\application\src\fastvideoassembly\icons"; Flags: ignoreversion
Source: "..\src\fastvideoassembly\styles\*.qss"; DestDir: "{app}\application\src\fastvideoassembly\styles"; Flags: ignoreversion
Source: "THIRD-PARTY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "uv.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "vendor.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "python.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PythonUrl}"; DestDir: "{localappdata}\{#MyAppName}\Cache\downloads"; DestName: "python-{#PythonHash}.tar.gz"; ExternalSize: {#PythonDownloadSize}; Hash: "{#PythonHash}"; Flags: external download ignoreversion onlyifdoesntexist uninsneveruninstall
Source: "{localappdata}\{#MyAppName}\Cache\downloads\python-{#PythonHash}.tar.gz"; DestDir: "{tmp}"; ExternalSize: {#PythonTarSize}; Hash: "{#PythonHash}"; Flags: external extractarchive ignoreversion
Source: "{tmp}\python-{#PythonHash}.tar"; DestDir: "{app}\runtime"; ExternalSize: {#PythonSize}; Hash: "{#PythonTarHash}"; Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
; Matches platformdirs.user_cache_path(MyAppName, appauthor=False) on Windows.
; Keep hash-addressed archives across upgrades and uninstall; verify on extraction.
Source: "{#UvUrl}"; DestDir: "{localappdata}\{#MyAppName}\Cache\downloads"; DestName: "uv-{#UvHash}.zip"; ExternalSize: {#UvDownloadSize}; Hash: "{#UvHash}"; Flags: external download ignoreversion onlyifdoesntexist uninsneveruninstall
Source: "{localappdata}\{#MyAppName}\Cache\downloads\uv-{#UvHash}.zip"; DestDir: "{app}\tools\uv"; ExternalSize: {#UvSize}; Hash: "{#UvHash}"; Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "{#FFmpegUrl}"; DestDir: "{localappdata}\{#MyAppName}\Cache\downloads"; DestName: "ffmpeg-{#FFmpegHash}.zip"; ExternalSize: {#FFmpegDownloadSize}; Hash: "{#FFmpegHash}"; Flags: external download ignoreversion onlyifdoesntexist uninsneveruninstall
Source: "{localappdata}\{#MyAppName}\Cache\downloads\ffmpeg-{#FFmpegHash}.zip"; DestDir: "{app}\tools\ffmpeg"; ExternalSize: {#FFmpegSize}; Hash: "{#FFmpegHash}"; Flags: external extractarchive ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\application\.venv\Scripts\pythonw.exe"; Parameters: "-I -m fastvideoassembly.installed"; WorkingDir: "{app}"; IconFilename: "{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\application\.venv\Scripts\pythonw.exe"; Parameters: "-I -m fastvideoassembly.installed"; WorkingDir: "{app}"; IconFilename: "{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"

[Run]
Filename: "{app}\tools\uv\uv.exe"; Parameters: "sync --project ""{app}\application"" --python ""{app}\runtime\python\python.exe"" --no-python-downloads --locked --no-dev --no-editable --no-config --no-cache"; StatusMsg: "Installing locked Python dependencies..."; Flags: runhidden logoutput
; postinstall is checked by default; omit unchecked to launch on Finish.
Filename: "{app}\application\.venv\Scripts\pythonw.exe"; Parameters: "-I -m fastvideoassembly.installed"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\application\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\runtime"

[Registry]
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%V"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\Drive\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\FastVideoAssembly"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\FastVideoAssembly"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\FastVideoAssembly"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\FastVideoAssembly"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\FastVideoAssembly"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\FastVideoAssembly"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\application\src\fastvideoassembly\FastVideoAssembly-blue.ico"""; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\FastVideoAssembly"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Flags: dontcreatekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\FastVideoAssembly\command"; ValueType: string; ValueData: """{app}\application\.venv\Scripts\pythonw.exe"" -I -m fastvideoassembly.installed ""%1"""; Flags: dontcreatekey

