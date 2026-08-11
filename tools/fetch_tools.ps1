<#
  Downloads the ONE external tool this program needs: adb (Android platform-tools).
  Run once on your Windows build machine:

      powershell -ExecutionPolicy Bypass -File tools\fetch_tools.ps1

  Produces:
      tools\platform-tools\adb.exe   (+ the two dll files adb needs)

  (This fixed-payload build installs already-signed APKs, so it does NOT need
  Java, apktool or the Android build-tools — only adb.)
#>
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "Downloading Android platform-tools (adb)…"
Invoke-WebRequest -Uri "https://dl.google.com/android/repository/platform-tools-latest-windows.zip" -OutFile "pt.zip"
Expand-Archive -Force "pt.zip" "."
Remove-Item "pt.zip"

Write-Host "Done. tools\platform-tools\adb.exe is ready."
