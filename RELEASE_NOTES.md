# 晴片 v0.1.1 · Windows 64 位与 Mac 版

新增 Windows x64 免安装版，同版本提供 Apple Silicon Mac 下载包。默认“全自动自然”：导入照片后，直接批量导出。

## 下载与打开

- **Windows 10 1809+ / Windows 11，64 位 x64**：下载 `Qingpian-0.1.1-Windows-x64.zip`，完整解压，进入“晴片”文件夹，双击 `晴片.exe`。
- **Apple Silicon Mac，macOS 14+**：下载 `Qingpian-0.1.1-macOS-arm64.zip`，解压后双击 `晴片.app`。
- 两个系统均自带 Python、Qt、JPG / HEIC 处理依赖，使用时不需要安装 Python。照片在本机处理。
- 附件中的 `SHA256SUMS.txt` 可核验下载包；GitHub 自动生成的 `Source code` 是源码，不是桌面应用。

## 功能

- JPG、JPEG、HEIC、HEIF 批量导入与可选递归扫描。
- 逐张自动分析曝光、暗部、高光、对比度、色彩和小幅白平衡。
- 前后对比、默认收起手动参数，并保留高级预设。
- 原尺寸高品质 sRGB JPG 导出，保留原片，同名结果自动编号。
- 可选保留拍摄信息，支持取消与单张失败后继续处理。

## 验证与构建

- Windows 在原生 x64 环境构建，运行照片与 GUI 自动化检查。
- 对最终 Windows ZIP 进行解压、SHA-256、AMD64 PE 校验，并用其中的实际 `.exe` 验证原生 Qt 界面、JPG / HEIC 导入、默认自动批量导出与原片不变。
- Mac 检查版本、arm64 架构、随附库最低系统版本、解压后的签名完整性与启动。
- 构建依赖、源码提交和许可文本随应用保留。测试使用生成的图片。

## 首次运行与边界

- Windows 包未经过 Authenticode 数字签名，首次运行可能出现系统来源验证提示。
- Mac 包使用 ad-hoc 签名，未做 Apple Developer ID 签名与 Apple 公证。首次打开如受阻，请确认下载来自本仓库，并参考 [Apple 官方说明](https://support.apple.com/en-us/102445)。
- Mac 为 arm64 版；Windows 为 x64 版，均不是跨架构通用包。
- 输出为普通 SDR JPG，不保留 HEIC HDR 增益图、动态照片视频或景深数据。
- 自动调色会受场景与审美影响，极暗、彩灯和已修过的照片建议抽样查看。自动处理不能恢复原片已经丢失的细节。
