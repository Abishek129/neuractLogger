# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

BASE_DIR = Path.cwd()
TRAY_DIR = BASE_DIR / 'apps' / 'agent-tray'
CORE_DIRS = [
    BASE_DIR / 'dist' / 'neuract-agent-core',
    BASE_DIR / 'dist' / 'plc-agent-core',
]
DATA_FILES = []
for core_dir in CORE_DIRS:
    if core_dir.exists():
        DATA_FILES.append((str(core_dir), 'agent-core'))
        break

a = Analysis(
    ['apps\\agent-tray\\main.py'],
    pathex=[str(TRAY_DIR)],
    binaries=[],
    datas=DATA_FILES,
    hiddenimports=['autostart', 'health', 'logging_conf', 'process_manager'],
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
    name='neuract-agent-tray',
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
    icon=['apps\\agent-tray\\assets\\tray.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='neuract-agent-tray',
)


