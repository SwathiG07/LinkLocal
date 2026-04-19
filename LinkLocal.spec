# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

# Get the current directory 
curr_dir = os.path.abspath(os.getcwd())

# Use collect_all to ensure EVERYTHING in linklocal is included
datas, binaries, hiddenimports = collect_all('linklocal')

a = Analysis(
    ['main.py'],
    pathex=[curr_dir],
    binaries=binaries,
    datas=datas + [('linklocal/superuser/templates', 'linklocal/superuser/templates')],
    hiddenimports=hiddenimports + [
        'linklocal.gui',
        'linklocal.cli',
        'linklocal.peer',
        'linklocal.storage',
        'linklocal.group',
        'linklocal.discovery',
        'linklocal.utils',
        'linklocal.config',
        'linklocal.superuser.dashboard'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LinkLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
