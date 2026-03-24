# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Memento system-tray daemon (MementoTray.exe).
# Build with:  pyinstaller MementoTray.spec --noconfirm

import os, sys

block_cipher = None

_PY_DIR = sys.base_prefix
_PY_DLL = os.path.join(_PY_DIR, 'python313.dll')

a = Analysis(
    ['tray_app.py'],
    pathex=[],
    binaries=[
        (_PY_DLL, '.'),
    ],
    datas=[
        ('Images', 'Images'),
    ],
    hiddenimports=[
        'pystray',
        'PIL',
        'PIL.Image',
        'winsound',
        'winreg',
        'plyer',
        'plyer.platforms.win.notification',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MementoTray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='Images\\memento.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MementoTray',
)
