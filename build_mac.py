"""Build a self-contained .app on the current Mac architecture.

Run after installing requirements.txt and pyinstaller>=6.16,<7.
"""

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image
from PySide6.QtWidgets import QApplication
from photo_tool.gui import app_icon

root = Path(__file__).resolve().parent
os.chdir(root)
build = root / "build"
build.mkdir(exist_ok=True)
app = QApplication([])
app_icon().pixmap(1024, 1024).save(str(build / "icon.png"))
with Image.open(build / "icon.png") as image:
    image.save(build / "qingpian.icns", format="ICNS")

subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "晴片", "--osx-bundle-identifier", "local.qingpian.photo",
    "--icon", str(build / "qingpian.icns"), "--collect-all", "pillow_heif",
    "--copy-metadata", "PySide6-Essentials", "--copy-metadata", "shiboken6",
    "--copy-metadata", "Pillow", "--copy-metadata", "numpy",
    "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "numpy.f2py", "app.py",
], check=True)
print(f"已生成：{root / 'dist' / '晴片.app'}")

