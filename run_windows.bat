@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo [X] Run setup_windows.bat first. / شغّل setup_windows.bat أول
  pause
  exit /b 1
)
rem Drag a project .json file onto this .bat, or it uses the family example.
set "CONFIG=%~1"
if "%CONFIG%"=="" set "CONFIG=examples\family.json"
set /p SEEDS="Seeds (Enter = 1 2 3 4): "
if "%SEEDS%"=="" set "SEEDS=1 2 3 4"
echo.
echo Generating plans for %CONFIG% ...
.venv\Scripts\python -m floorplan "%CONFIG%" --seeds %SEEDS% --out out --formats svg dxf glb json
if errorlevel 1 (
  echo [X] Something went wrong - see the message above.
  pause
  exit /b 1
)
echo.
echo [OK] Files are in the "out" folder. / الملفات بمجلد out
start "" "%~dp0out"
pause
