@echo off
REM Build the buyer-facing relay into ONE .exe. Run this on Windows.
REM
REM   agent\build_relay.bat   ->   dist\AxolotlRelay.exe
REM
REM PyInstaller cannot cross-compile, so this must run on Windows even though
REM the rest of the project is developed elsewhere.
setlocal

echo.
echo   Building AxolotlRelay.exe
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo   ERROR: Python is not on PATH. Install it from python.org first,
  echo          and tick "Add Python to PATH" in the installer.
  exit /b 1
)

python -m pip install --quiet --upgrade pyinstaller websockets
if errorlevel 1 (
  echo   ERROR: could not install the build dependencies.
  exit /b 1
)

python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\relay ^
    agent\relay.spec
if errorlevel 1 (
  echo   ERROR: the build failed. Scroll up for the reason.
  exit /b 1
)

echo.
echo   Done:  dist\AxolotlRelay.exe
echo.
echo   Give that ONE file to buyers with a FAW B70. They double-click it,
echo   leave the window open, and press Connect on the website.
echo.
echo   NOTE: it is unsigned, so Windows SmartScreen will warn on first run
echo         ("More info" -^> "Run anyway"). A code-signing certificate
echo         removes that warning; see agent\README.md.
echo.
endlocal
