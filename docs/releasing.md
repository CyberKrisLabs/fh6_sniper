# Releasing FH6 Sniper

## How it works

Pushing a version tag triggers the **Release** GitHub Actions workflow, which:

1. Builds `FH6 Sniper.exe` with PyInstaller
2. Packages it into `FH6_Sniper_Installer_vX.Y.Z.exe` with Inno Setup
3. Creates a GitHub Release with the installer attached and auto-generated release notes

## Cutting a release

1. Bump `__version__` in `app.py`:
   ```python
   __version__ = "2.1.0"
   ```

2. Commit and push:
   ```powershell
   git add app.py
   git commit -m "Bump version to 2.1.0"
   git push
   ```

3. Tag and push the tag — this triggers the release workflow:
   ```powershell
   git tag v2.1.0
   git push origin v2.1.0
   ```

4. Watch the workflow at https://github.com/CyberKrisLabs/fh6_sniper/actions

5. When it finishes, the release is live at https://github.com/CyberKrisLabs/fh6_sniper/releases

## Building locally

```powershell
pip install pyinstaller
pyinstaller "FH6 Sniper.spec"
# exe appears at dist\FH6 Sniper.exe

# Then build the installer (requires Inno Setup 6):
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
# installer appears at installer\Output\FH6_Sniper_Installer_v2.0.0.exe
```

## Updating the icon

Edit `tools/make_icon.py` and run:
```powershell
python tools/make_icon.py
```

This overwrites `assets/sniper.ico`. Commit the new `.ico` before building.

## Files

| File | Purpose |
|---|---|
| `FH6 Sniper.spec` | PyInstaller build spec (one-file exe, includes `assets/` and `docs/`) |
| `installer/installer.iss` | Inno Setup installer script |
| `.github/workflows/release.yml` | CI/CD — builds and publishes on version tag push |
| `tools/make_icon.py` | Generates `assets/sniper.ico` from code |
