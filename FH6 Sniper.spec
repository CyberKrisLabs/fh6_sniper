# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[
        # winrt ships its own msvcp140.dll — include it alongside the .pyd files
        (".venv/Lib/site-packages/winrt/msvcp140.dll", "."),
    ],
    datas=[
        ("assets", "assets"),
        ("docs", "docs"),
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
