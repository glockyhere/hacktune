@echo off
REM ===================================================================
REM  One-command Windows build. Run from the project root: build.bat
REM  Requires: Python 3.10+ installed and on PATH.
REM ===================================================================
setlocal

echo [1/4] Creating virtual environment...
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat || goto :err

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :err

echo [3/4] Building CarApkInstaller.exe...
pyinstaller --noconfirm build\CarApkInstaller.spec || goto :err

echo [4/4] Copying tools\ next to the exe...
if exist tools (
    xcopy /E /I /Y tools dist\tools >nul
) else (
    echo   WARNING: tools\ folder is empty. Run tools\fetch_tools.ps1 first,
    echo            or the exe will not find adb/apksigner/apktool at runtime.
)

echo.
echo Done.  Your program:  dist\CarApkInstaller.exe
echo Ship the whole dist\ folder (exe + tools\).  Do NOT ship keygen\.
goto :eof

:err
echo.
echo BUILD FAILED. See the error above.
exit /b 1
