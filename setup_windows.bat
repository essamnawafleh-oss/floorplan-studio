@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Floor Plan Studio - Setup / تثبيت
echo ============================================
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [X] Python is not installed. / بايثون مش مثبت
  echo     Download it from https://www.python.org/downloads/
  echo     IMPORTANT: tick "Add python.exe to PATH" during install.
  echo     مهم: فعّل خيار Add python.exe to PATH وقت التثبيت
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating environment...
  python -m venv .venv || (echo [X] Failed to create environment & pause & exit /b 1)
)
echo Installing libraries (first time takes a minute)...
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt -q || (echo [X] Install failed & pause & exit /b 1)
echo.
echo [OK] Done! Now double-click run_windows.bat
echo [OK] خلص! هسا اكبس دبل كليك على run_windows.bat
pause
