; Inno Setup script - builds FloorPlanStudio-Setup.exe from dist\FloorPlanStudio
#define AppVersion GetEnv("APP_VERSION")
#if AppVersion == ""
  #define AppVersion "0.3.0"
#endif

[Setup]
AppId={{53C6CFC2-4870-46B1-A447-061EE217A186}
AppName=Floor Plan Studio
AppVersion={#AppVersion}
AppPublisher=Essam Nawafleh
AppPublisherURL=https://github.com/essamnawafleh-oss/floorplan-studio
DefaultDirName={localappdata}\Programs\FloorPlanStudio
DefaultGroupName=Floor Plan Studio
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=FloorPlanStudio-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\FloorPlanStudio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\Arabic.isl")
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\FloorPlanStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Floor Plan Studio"; Filename: "{app}\FloorPlanStudio.exe"
Name: "{autodesktop}\Floor Plan Studio"; Filename: "{app}\FloorPlanStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FloorPlanStudio.exe"; Description: "{cm:LaunchProgram,Floor Plan Studio}"; Flags: nowait postinstall skipifsilent
