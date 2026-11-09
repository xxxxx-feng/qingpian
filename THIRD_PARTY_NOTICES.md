# 第三方组件说明

晴片的 Mac 应用包包含以下第三方运行组件。各组件的许可、版权和再分发条件分别适用，不因本项目公开而改变。

| 组件 | 用途 | 上游 |
| --- | --- | --- |
| CPython | Python 运行时 | https://www.python.org/ |
| Qt / PySide6 Essentials / Shiboken | 本地桌面界面 | https://doc.qt.io/qtforpython-6/ |
| Pillow | 图像与色彩处理 | https://pillow.readthedocs.io/ |
| NumPy | 像素计算 | https://numpy.org/ |
| pillow-heif / libheif 及其随附编解码组件 | HEIC / HEIF 支持 | https://github.com/bigcat88/pillow_heif |
| PyInstaller bootloader | 独立应用启动器 | https://pyinstaller.org/ |

`THIRD_PARTY_LICENSES.txt` 收录当前构建依赖提供的许可证和随附库说明，以及 CPython、GNU LGPL v3 / GPL v3 文本；PyInstaller 的文本包含其 bootloader 例外。它会与本文件一起放入 `晴片.app/Contents/Resources/`。

具体依赖版本和源码提交记录在应用中的 `Contents/Resources/release-info.json`，同时参考仓库内的 `requirements-tested.txt`。升级构建环境依赖后，应重新执行 `python generate_notices.py`，核对结果再发布。

本文件是组件来源与许可文本的索引，不代表对本项目另行授予 GNU GPL 或其他项目级许可。本项目暂未添加独立的项目级许可证。
