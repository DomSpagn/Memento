# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the main Memento GUI application.
# Build with:  pyinstaller Memento.spec --noconfirm

import os
import sys
import flet as _flet_mod
import flet_desktop as _flet_desktop_mod
_flet_path         = os.path.dirname(_flet_mod.__file__)
_flet_desktop_path = os.path.dirname(_flet_desktop_mod.__file__)

block_cipher = None

_PY_DIR = sys.base_prefix
_PY_DLL = os.path.join(_PY_DIR, 'python313.dll')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        (_PY_DLL, '.'),
    ],
    datas=[
        ('Images',          'Images'),
        (os.path.join('User Manuals', 'manual_en.html'), 'User Manuals'),
        (os.path.join('User Manuals', 'manual_it.html'), 'User Manuals'),
        (os.path.join('ReleaseNotes', 'release_notes_en.html'), 'ReleaseNotes'),
        (os.path.join('ReleaseNotes', 'release_notes_it.html'), 'ReleaseNotes'),
        ('translations.py', '.'),
        (_flet_path,         'flet'),
        (_flet_desktop_path, 'flet_desktop'),
    ],
    hiddenimports=[
        'flet_desktop',
        'flet_core',
        'reportlab.graphics.barcode.ecc200datamatrix',
        'reportlab.graphics.barcode.code39',
        'reportlab.graphics.barcode.code93',
        'reportlab.graphics.barcode.code128',
        'reportlab.graphics.barcode.usps',
        'reportlab.graphics.barcode.usps4s',
        'reportlab.graphics.barcode.qr',
        'reportlab.graphics.barcode.eanbc',
        'reportlab.graphics.barcode.lto',
        'reportlab.graphics.barcode.fourstate',
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
    name='Memento',
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
    name='Memento',
)
