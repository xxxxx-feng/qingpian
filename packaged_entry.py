"""Windows entry point and private packaged-dependency smoke check."""
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def packaged_self_test(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "self-test-result.json"
    window = None
    app = None
    try:
        import numpy as np
        from PIL import Image
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        from photo_tool.gui import MainWindow, STYLE
        from photo_tool.processing import DEFAULT_PRESET, source_created_at

        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        app.setStyleSheet(STYLE)
        yy, xx = np.mgrid[:180, :240]
        pixels = np.stack([25+xx/3, 30+yy/3, 35+xx/5], axis=2).astype(np.uint8)
        input_root = directory / "原照片"
        (input_root / "家人").mkdir(parents=True)
        (input_root / "旅行").mkdir()
        paths = [input_root/"家人/测试暗光.jpg", input_root/"家人/测试逆光.heic",
                 input_root/"旅行/测试风景.jpg"]
        Image.fromarray(pixels).save(paths[0], quality=95)
        Image.fromarray(pixels).save(paths[1], format="HEIF", quality=90)
        Image.fromarray(pixels).save(paths[2], quality=95)
        original_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]

        def wait_until(predicate):
            deadline = time.monotonic()+45
            while not predicate():
                app.processEvents()
                time.sleep(.02)
                if time.monotonic()>deadline:
                    raise TimeoutError("Packaged GUI operation timed out")
            app.processEvents()

        window = MainWindow()
        window.show()
        assert window.preset.currentText()==DEFAULT_PRESET
        window.add_paths([input_root])
        wait_until(lambda: len(window.items)==3 and window.view.after is not None)
        destination = directory/"导出结果"
        window.begin_export(paths, destination)
        wait_until(lambda: not window.exporting)
        assert not window.failures, window.failures
        exports = sorted(destination.rglob("*.jpg"))
        assert len(exports)==3
        days = [source_created_at(path).strftime('%Y-%m-%d') for path in paths]
        assert days[0] == days[1], days
        assert {path.name for path in (destination/'家人').glob('*.jpg')} == {f'{days[0]}_1.jpg', f'{days[0]}_2.jpg'}
        assert (destination/'旅行'/f'{days[2]}.jpg').is_file()
        for path in exports:
            with Image.open(path) as image:
                image.load()
                assert image.size==(240,180)
                assert image.info.get("icc_profile")
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]==original_hashes
        wait_until(lambda: not any(pool.activeThreadCount() for pool in (
            window.pool, window.scan_pool, window.export_pool)))
        assert window.grab().save(str(directory/"packaged-gui.png"))
        result = dict(status="passed", qt_platform=QGuiApplication.platformName(),
                      jpeg_heic_import=True, automatic_gui_export_count=len(exports),
                      original_files_unchanged=True, srgb_export=True,
                      original_creation_date_filenames=True, same_day_numbering=True,
                      original_directories_preserved=True)
        status = 0
    except Exception:
        result = dict(status="failed", traceback=traceback.format_exc())
        status = 1
    finally:
        if window is not None:
            window.hide()
            window.export_cancel.set()
            window.scan_cancel.set()
            window.preview_cancel.set()
            for pool in (window.pool, window.scan_pool, window.export_pool):
                pool.clear()
                pool.waitForDone(5000)
            if app is not None:
                app.processEvents()
            window.exporting = False
            window.close()
        if app is not None:
            app.processEvents()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return status


if __name__=="__main__":
    if len(sys.argv)==3 and sys.argv[1]=="--packaged-self-test":
        raise SystemExit(packaged_self_test(sys.argv[2]))
    from photo_tool.gui import main
    main()
