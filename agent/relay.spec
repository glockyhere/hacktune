# PyInstaller spec for the buyer-facing relay.
#
#   pyinstaller agent/relay.spec        (run this ON WINDOWS)
#   -> dist/AxolotlRelay.exe            single file, no Python needed
#
# console=True on purpose: the window IS the interface. It tells the buyer
# whether the car was found and when to go back to the browser, and it holds
# open on failure so a mistake can be read instead of flashing past.
#
# Cross-compiling is not possible: PyInstaller emits a binary for the OS it runs
# on, so a Windows .exe must be built on Windows. Use agent/build_relay.bat.
block_cipher = None

a = Analysis(
    ['relay.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['websockets'],
    hookspath=[],
    runtime_hooks=[],
    # Trim only the GUI/scientific stacks PyInstaller pulls in by reflex.
    #
    # Keep this list SHORT and boring. An earlier version also excluded 'email',
    # 'html', 'pydoc' and 'difflib' to shave a megabyte, and the exe then died on
    # startup with ModuleNotFoundError: no module named 'email' — urllib.request
    # imports it, and urllib.request is how the token is verified. A relay that
    # cannot start is worth far more than a megabyte. Anything added here must be
    # proven by RUNNING the built binary, not by reasoning about imports.
    excludes=['tkinter', 'numpy', 'PIL', 'matplotlib'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='AxolotlRelay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX-packed exes get flagged by antivirus far more
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
