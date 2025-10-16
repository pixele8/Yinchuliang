# -*- mode: python ; coding: utf-8 -*-

import PySide6
from pathlib import Path

block_cipher = None

project_root = Path(__file__).resolve().parent

hidden_imports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtPrintSupport",
]

datas = []
qt_base = Path(PySide6.__file__).resolve().parent
qt_plugins = qt_base / "plugins"
if qt_plugins.exists():
    datas.append((str(qt_plugins), "PySide6/plugins"))

sample_data = project_root / "kb_app" / "sample_data"
if sample_data.exists():
    datas.append((str(sample_data), "kb_app/sample_data"))


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
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
    name="OfflineKnowledgeApp",
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OfflineKnowledgeApp",
)
