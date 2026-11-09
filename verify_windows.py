"""Check the extracted release ZIP and execute its actual packaged GUI."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from build_windows import pe_machine


def main():
    if sys.platform!="win32":
        raise SystemExit("Run this verification on Windows.")
    root = Path(__file__).resolve().parent
    version = (root/"VERSION").read_text().strip()
    distribution = root/"dist/windows-x64"
    archive = distribution/f"Qingpian-{version}-Windows-x64.zip"
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected = (distribution/f"Qingpian-{version}-Windows-x64-SHA256SUMS.txt").read_text().split()[0]
    assert checksum==expected
    with tempfile.TemporaryDirectory(prefix="qingpian-windows-release-") as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(archive) as zipped:
            assert zipped.testzip() is None
            zipped.extractall(temporary/"解压目录")
        folder = temporary/"解压目录/晴片"
        executable = folder/"晴片.exe"
        assert pe_machine(executable)==0x8664
        info = json.loads((folder/"release-info.json").read_text(encoding="utf-8"))
        assert info['version']==version and info['architecture']=="x64"
        assert (folder/"_internal/THIRD_PARTY_LICENSES.txt").is_file()
        env = os.environ.copy()
        env.pop("QT_QPA_PLATFORM",None)
        env.pop("PYTHONPATH",None)
        check = temporary/"打包程序自检"
        subprocess.run([str(executable),"--packaged-self-test",str(check)],cwd=temporary,env=env,timeout=90,check=True)
        result = json.loads((check/"self-test-result.json").read_text(encoding="utf-8"))
        assert result['status']=="passed" and result['qt_platform']=="windows",result
        shutil.copy2(check/"packaged-gui.png",distribution/"windows-packaged-gui.png")
    report = dict(zip_integrity="passed",executable_machine="AMD64 / 0x8664",sha256=checksum,
                  native_gui_smoke_test=result,source_commit=info['source_commit'])
    (distribution/"windows-verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
