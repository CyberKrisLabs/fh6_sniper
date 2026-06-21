# -*- mode: python ; coding: utf-8 -*-

import os, site

def _find_winrt_dll():
    # Search all site-packages directories (handles both venv and global installs)
    for sp in site.getsitepackages():
        p = os.path.join(sp, "winrt", "msvcp140.dll")
        if os.path.isfile(p):
            return p
    # Local .venv fallback (developer workstation)
    fallback = os.path.join(".venv", "Lib", "site-packages", "winrt", "msvcp140.dll")
    if os.path.isfile(fallback):
        return fallback
    return None

_winrt_dll = _find_winrt_dll()
_binaries = [(_winrt_dll, ".")] if _winrt_dll else []

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=_binaries,
    datas=[
        ("assets", "assets"),
    ],
    hiddenimports=[
        "win32api",
        "win32con",
        "win32gui",
        "win32process",
        "win32print",
        # winrt OCR — imports are inside try/except so PyInstaller can't see them
        "winrt._winrt",
        "winrt._winrt_windows_foundation",
        "winrt._winrt_windows_graphics_imaging",
        "winrt._winrt_windows_media_ocr",
        "winrt._winrt_windows_storage_streams",
        "winrt.runtime",
        "winrt.runtime._internals",
        "winrt.runtime.interop",
        "winrt.system",
        "winrt.system.hresult",
        "winrt.windows.foundation",
        "winrt.windows.graphics.imaging",
        "winrt.windows.media.ocr",
        "winrt.windows.storage.streams",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # not used in the app — update check is try/except optional
        "requests",
        # we use PySide6, not tkinter (tkinter only appears in tools/shadow_mode.py)
        "tkinter",
        "_tkinter",
        # unused scientific/plotting stack (may be pulled in transitively)
        "matplotlib",
        # Python's own top-level test package — not needed at runtime
        # NOTE: do NOT exclude unittest — pyrect imports doctest which imports unittest
        "test",
    ],
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
    name="FH6 Sniper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir="%LOCALAPPDATA%\\FH6Sniper",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets\\sniper.ico"],
)
