# -*- mode: python ; coding: utf-8 -*-
# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

from PyInstaller.utils.hooks import collect_all

qtwebview2_datas, qtwebview2_binaries, qtwebview2_hiddenimports = collect_all(
    'qtwebview2'
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qtwebview2_binaries,
    datas=[('assets', 'assets'), ('prompts', 'prompts')] + qtwebview2_datas,
    hiddenimports=[
        'qtwebview2',
        'qtpy',
        'pythonnet',
        'clr',
        'clr_loader',
    ] + qtwebview2_hiddenimports,
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
    [],
    exclude_binaries=True,
    name='Bekki',
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
    icon=['assets/bekki.ico'],
    version='version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Bekki',
)
