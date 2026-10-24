"""Per-user Windows File Explorer integration."""

import sys
from pathlib import Path

from platformdirs import user_config_path
from PySide6.QtCore import QSettings

from . import APP_NAME

APP_MODULE = "fastvideoassembly"

CONTEXTS = (
    (r"Software\Classes\Directory\shell", "%1"),
    (r"Software\Classes\Directory\Background\shell", "%V"),
    (r"Software\Classes\Drive\shell", "%1"),
    (r"Software\Classes\SystemFileAssociations\.mp4\shell", "%1"),
    (r"Software\Classes\SystemFileAssociations\.mkv\shell", "%1"),
    (r"Software\Classes\SystemFileAssociations\.mov\shell", "%1"),
    (r"Software\Classes\SystemFileAssociations\.avi\shell", "%1"),
    (r"Software\Classes\SystemFileAssociations\.webm\shell", "%1"),
)


def install(module=APP_MODULE):
    import winreg

    executable = str(Path(sys.executable).resolve())
    launcher = [executable, "-I", "-m", module]
    icon_root = Path(__file__).resolve().parent

    settings = QSettings(
        str(user_config_path(APP_NAME, appauthor=False) / "settings.ini"),
        QSettings.Format.IniFormat,
    )
    icon_name = settings.value("appearance/icon", "blue")
    icon = f'"{icon_root / "icons" / (icon_name + ".ico")}"'
    for root, target in CONTEXTS:
        menu_key = rf"{root}\{APP_NAME}"
        command = " ".join(f'"{part}"' for part in [*launcher, target])
        print(f"File Explorer command ({root}): {command}")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, menu_key, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"Open in {APP_NAME}")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon)
            if root.startswith(r"Software\Classes\SystemFileAssociations"):
                winreg.SetValueEx(key, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, menu_key + r"\command", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    print(f"[OK] Installed {len(CONTEXTS)} File Explorer context menu entries.")
    return 0
