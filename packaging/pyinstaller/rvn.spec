# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ROOT = Path.cwd()


def _metadata(package: str):
    try:
        return copy_metadata(package)
    except Exception:
        return []


def _submodules(package: str) -> list[str]:
    try:
        return collect_submodules(package)
    except Exception:
        return []


datas = []
for package in ("rvn", "typer", "click", "rich", "httpx", "keyring"):
    datas += _metadata(package)

hiddenimports = []
hiddenimports += _submodules("keyring.backends")
hiddenimports += [
    "secretstorage",
    "secretstorage.collection",
    "secretstorage.item",
    "jeepney",
    "jeepney.auth",
    "jeepney.bus",
    "jeepney.io.blocking",
    "jeepney.wrappers",
]

a = Analysis(
    [str(ROOT / "packaging" / "pyinstaller" / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="rvn",
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
    name="rvn",
)
