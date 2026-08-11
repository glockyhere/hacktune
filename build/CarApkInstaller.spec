# PyInstaller spec. Build from the PROJECT ROOT on Windows:
#     pyinstaller build\CarApkInstaller.spec
#
# Produces a SINGLE file: dist\CarApkInstaller.exe (no console window).
# The five pre-signed/patched APKs (payload\) are bundled INSIDE the exe, so the
# program is truly self-contained for its job. The only external tool needed is
# adb, which lives in a `tools\` folder next to the exe (fetch_tools.ps1).

import os

block_cipher = None

# APKs are NOT bundled — the program downloads them from config.APK_BASE_URL at
# runtime and verifies each one's pinned SHA-256. So the exe stays small (~15 MB).

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['cryptography'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['keygen'],          # never bundle the private signing tools
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='CarApkInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    icon='resources/app.ico' if os.path.exists('resources/app.ico') else None,
)
