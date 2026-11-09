"""Collect license texts for the installed release environment.

GNU license texts are fetched from official HTTPS addresses. Commit the result
with the source so ordinary app builds do not require these downloads.
"""

import platform
import sys
import sysconfig
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = ("Pillow", "numpy", "pillow-heif", "PySide6-Essentials", "shiboken6", "pyinstaller")


def main():
    sections = ["Qingpian: bundled third-party licenses and notices\n"
                "These texts apply to third-party components, not a new project-level license.\n"]
    for name in PACKAGES:
        distribution = metadata.distribution(name)
        expression = (distribution.metadata.get("License-Expression")
                      or distribution.metadata.get("License") or "See upstream licensing terms")
        sections.append(f"\n{'=' * 72}\n{name} {distribution.version}\nDeclared license: {expression}\n")
        paths = sorted(path for path in distribution.files or []
                       if any(word in Path(path).name.lower() for word in ("license", "copying")))
        for relative in paths:
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                sections.append(f"\n--- {relative} ---\n" + path.read_text(encoding="utf-8", errors="replace"))
        if name in ("PySide6-Essentials", "shiboken6"):
            sections.append("Qt for Python / Shiboken: The Qt Company Ltd. and contributors.\n"
                            "Upstream: https://doc.qt.io/qtforpython-6/\n"
                            "GNU LGPL v3 and GPL v3 texts are reproduced below.\n")
    python_license = next((path for path in (
        Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
    ) if path.is_file()), None)
    if python_license is None:
        raise SystemExit("Python's LICENSE.txt was not found; collect its license before release.")
    sections.append(f"\n{'=' * 72}\nCPython {platform.python_version()}\n" + python_license.read_text(encoding="utf-8", errors="replace"))
    for name, url in (("GNU LGPL v3", "https://www.gnu.org/licenses/lgpl-3.0.txt"),
                      ("GNU GPL v3", "https://www.gnu.org/licenses/gpl-3.0.txt")):
        request = urllib.request.Request(url, headers={"User-Agent": "Qingpian-license-collector"})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
        if "GNU" not in text or len(text) < 5000:
            raise SystemExit(f"Unexpected license response: {url}")
        sections.append(f"\n{'=' * 72}\n{name}\nSource: {url}\n\n{text}")
    destination = ROOT / "THIRD_PARTY_LICENSES.txt"
    destination.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(f"Collected dependency license texts: {destination.name}")


if __name__ == "__main__":
    main()
