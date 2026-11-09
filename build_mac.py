"""Build a versioned, self-contained Mac app and release ZIP.

Install requirements.txt and pyinstaller>=6.16,<7 before running this file.
The output architecture follows the Python interpreter used for this build.
"""

import hashlib
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image
from PySide6.QtWidgets import QApplication
from photo_tool.gui import app_icon


def verify_minimum_macos(bundle, minimum="14.0"):
    """Reject a bundle whose native dependencies exceed the advertised target."""
    target = tuple(int(part) for part in minimum.split(".")) + (0,)
    magics = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
              b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
    for path in (bundle / "Contents").rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as handle:
            if handle.read(4) not in magics:
                continue
        lines = subprocess.check_output(["/usr/bin/otool", "-l", str(path)], text=True).splitlines()
        for index, line in enumerate(lines):
            command = line.strip()
            if command not in ("cmd LC_BUILD_VERSION", "cmd LC_VERSION_MIN_MACOSX"):
                continue
            key = "minos " if command == "cmd LC_BUILD_VERSION" else "version "
            for entry in lines[index + 1:index + 8]:
                if entry.strip().startswith(key):
                    version = entry.strip().split()[1]
                    parts = tuple(int(part) for part in version.split("."))
                    parts += (0,) * (3 - len(parts))
                    if parts > target:
                        raise SystemExit(f"{path.name} requires macOS {version}; target is {minimum}. "
                                         "Use the pinned requirements-tested.txt environment.")
                    break


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    if sys.platform != "darwin":
        raise SystemExit("This builder must run on macOS.")
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("VERSION must contain a three-part numeric version.")
    notices = root / "THIRD_PARTY_LICENSES.txt"
    if not notices.is_file():
        raise SystemExit("Run generate_notices.py before building.")
    build = root / "build"
    build.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app_icon().pixmap(1024, 1024).save(str(build / "icon.png"))
    with Image.open(build / "icon.png") as image:
        image.save(build / "qingpian.icns", format="ICNS")
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "晴片", "--osx-bundle-identifier", "local.qingpian.photo",
        "--icon", str(build / "qingpian.icns"), "--collect-all", "pillow_heif",
        "--copy-metadata", "PySide6-Essentials", "--copy-metadata", "shiboken6",
        "--copy-metadata", "Pillow", "--copy-metadata", "numpy",
        "--add-data", f"{notices}:.",
        "--add-data", f"{root / 'THIRD_PARTY_NOTICES.md'}:.",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtTest",
        "--exclude-module", "numpy.f2py", "app.py",
    ], check=True)
    bundle = root / "dist" / "晴片.app"
    info_path = bundle / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    info.update(CFBundleShortVersionString=version, CFBundleVersion=version,
                LSMinimumSystemVersion="14.0")
    with info_path.open("wb") as handle:
        plistlib.dump(info, handle)
    try:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        source_commit = "source archive"
    dependencies = {name: metadata.version(name) for name in (
        "Pillow", "numpy", "pillow-heif", "PySide6-Essentials", "shiboken6", "pyinstaller")}
    build_info = dict(version=version, architecture=platform.machine(),
                      minimum_macos="14.0", source_commit=source_commit,
                      python=platform.python_version(), dependencies=dependencies,
                      built_at_utc=datetime.now(timezone.utc).isoformat(),
                      signing="ad-hoc", notarized=False)
    (bundle / "Contents" / "Resources" / "release-info.json").write_text(
        json.dumps(build_info, ensure_ascii=False, indent=2) + "\n")
    verify_minimum_macos(bundle)
    # Resource changes need a new ad-hoc signature; this is not Apple notarization.
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    architecture = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x86_64"}.get(
        platform.machine(), platform.machine())
    archive = root / "dist" / f"Qingpian-{version}-macOS-{architecture}.zip"
    subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(bundle), str(archive)], check=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = root / "dist" / f"Qingpian-{version}-SHA256SUMS.txt"
    checksums.write_text(f"{digest}  {archive.name}\n")
    print(f"App: {bundle}\nRelease asset: {archive}\nSHA-256: {checksums}")


if __name__ == "__main__":
    main()

