# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['agent\\run_agent.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['fastapi', 'uvicorn', 'sqlalchemy', 'sqlmodel', 'apscheduler', 'icmplib', 'psutil', 'pymodbus', 'opcua', 'opcua.ua', 'opcua.common', 'opcua.crypto', 'cryptography'],
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
    name='plclogger-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='plclogger-agent',
)
