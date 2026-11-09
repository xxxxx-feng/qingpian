"""Build a self-contained Windows x64 portable folder and ZIP on Windows."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata


def pe_machine(path):
    with Path(path).open("rb") as handle:
        if handle.read(2)!=b"MZ":
            raise ValueError("Not a Windows executable")
        handle.seek(0x3c)
        offset = struct.unpack("<I", handle.read(4))[0]
        handle.seek(offset)
        if handle.read(4)!=b"PE\0\0":
            raise ValueError("Invalid PE header")
        return struct.unpack("<H", handle.read(2))[0]


def main():
    if sys.platform!="win32" or struct.calcsize("P")!=8 or platform.machine().lower() not in ("amd64","x86_64"):
        raise SystemExit("Use Windows x64 with 64-bit Python 3.12 for this build.")
    root = Path(__file__).resolve().parent
    os.chdir(root)
    version = (root/"VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+",version):
        raise SystemExit("Invalid VERSION")
    notices = root/"THIRD_PARTY_LICENSES.txt"
    if not notices.is_file():
        raise SystemExit("Run generate_notices.py before building.")
    os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from photo_tool.gui import app_icon
    app = QApplication.instance() or QApplication([])
    build = root/"build/windows-x64"
    build.mkdir(parents=True,exist_ok=True)
    app_icon().pixmap(1024,1024).save(str(build/"icon.png"))
    with Image.open(build/"icon.png") as image:
        image.save(build/"qingpian.ico",format="ICO",sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    numbers = tuple(int(p) for p in version.split("."))+(0,)
    version_text = f'''VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r},prodvers={numbers!r},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','Qingpian'),StringStruct('FileDescription','晴片照片自动调色'),StringStruct('FileVersion','{version}'),StringStruct('OriginalFilename','晴片.exe'),StringStruct('ProductName','晴片'),StringStruct('ProductVersion','{version}')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])'''
    (build/"version.txt").write_text(version_text,encoding="utf-8")
    distribution = root/"dist/windows-x64"
    subprocess.run([
        sys.executable,"-m","PyInstaller","--noconfirm","--clean","--onedir","--windowed",
        "--name","晴片","--distpath",str(distribution),"--workpath",str(build/"pyinstaller"),
        "--icon",str(build/"qingpian.ico"),"--version-file",str(build/"version.txt"),
        "--collect-all","pillow_heif","--copy-metadata","Pillow","--copy-metadata","numpy",
        "--copy-metadata","PySide6-Essentials","--copy-metadata","shiboken6",
        "--add-data",f"{notices};.","--add-data",f"{root/'THIRD_PARTY_NOTICES.md'};.",
        "--exclude-module","PySide6.QtQml","--exclude-module","PySide6.QtQuick",
        "--exclude-module","PySide6.QtNetwork","--exclude-module","PySide6.QtTest",
        "--exclude-module","numpy.f2py","packaged_entry.py",
    ],check=True)
    folder = distribution/"晴片"
    executable = folder/"晴片.exe"
    if pe_machine(executable)!=0x8664:
        raise SystemExit("Built executable is not AMD64.")
    source_commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    info = dict(version=version,architecture="x64",minimum_windows="10 1809",
                source_commit=source_commit,python=platform.python_version(),
                dependencies={name:metadata.version(name) for name in (
                    "Pillow","numpy","pillow-heif","PySide6-Essentials","shiboken6","pyinstaller")},
                built_at_utc=datetime.now(timezone.utc).isoformat(),authenticode_signed=False)
    (folder/"release-info.json").write_text(json.dumps(info,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (folder/"使用说明.txt").write_text(
        "晴片 · 全自动照片调色\n\n请完整解压整个文件夹，再双击「晴片.exe」。无需安装 Python。\n"
        "适用于 Windows 10 1809+ / Windows 11，64 位 x64。\n"
        "导入照片后直接批量导出；原片保留，处理在本机完成。\n"
        "本版本未做 Authenticode 数字签名，首次运行可能出现系统来源验证提示。\n"
        "项目与下载：https://github.com/xxxxx-feng/qingpian\n",encoding="utf-8-sig")
    archive = Path(shutil.make_archive(str(distribution/f"Qingpian-{version}-Windows-x64"),"zip",distribution,"晴片"))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (distribution/f"Qingpian-{version}-Windows-x64-SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n",encoding="utf-8")
    print(f"Windows x64 app: {executable}\nRelease asset: {archive}\nSHA-256: {checksum}")


if __name__=="__main__":
    main()
