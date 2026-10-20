"""Create Windows shortcuts (Desktop + Start Menu) for PixelForge AI Studio.

Run from the project folder:
    .venv\\Scripts\\python.exe tools\\create_shortcut.py

It also (re)generates assets/pixelforge.ico from the app logo. The shortcut
starts the app with pythonw.exe, so no console window appears.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICON_PATH = PROJECT_ROOT / "assets" / "pixelforge.ico"
SHORTCUT_NAME = "PixelForge AI Studio.lnk"


def build_icon(path: Path = ICON_PATH) -> Path:
    """Render the in-app logo to a multi-resolution .ico file."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(PROJECT_ROOT))
    from PySide6.QtWidgets import QApplication

    from services.qt_image import qimage_to_pil
    from ui.sidebar import logo_pixmap

    _app = QApplication.instance() or QApplication([])
    image = qimage_to_pil(logo_pixmap(256).toImage())
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcuts(icon: Path) -> list[Path]:
    """Create the shortcuts through the Windows Script Host COM object."""
    pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        raise SystemExit(f"Could not find {pythonw}. Create the virtual environment first.")
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$targets = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
foreach ($folder in $targets) {{
    $path = Join-Path $folder {_ps_quote(SHORTCUT_NAME)}
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = {_ps_quote(str(pythonw))}
    $link.Arguments = {_ps_quote('"' + str(PROJECT_ROOT / 'main.py') + '"')}
    $link.WorkingDirectory = {_ps_quote(str(PROJECT_ROOT))}
    $link.IconLocation = {_ps_quote(str(icon) + ',0')}
    $link.Description = 'PixelForge AI Studio - AI design studio'
    $link.WindowStyle = 1
    $link.Save()
    Write-Output $path
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Creating shortcuts failed:\n{result.stderr.strip()}")
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Shortcut creation is only supported on Windows.")
    icon = build_icon()
    print(f"Icon: {icon}")
    for path in create_shortcuts(icon):
        print(f"Shortcut: {path}")


if __name__ == "__main__":
    main()
