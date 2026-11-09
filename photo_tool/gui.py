"""Native Qt interface. Image work always runs outside the UI thread."""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImage,
                           QKeySequence, QLinearGradient, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QSplitter, QVBoxLayout,
                               QWidget)

from .processing import (Adjustments, DEFAULT_PRESET, PRESETS, SUPPORTED_EXTENSIONS, adjust_photo,
                         collect_photos, export_batch, load_photo)


STYLE = """
QMainWindow, QWidget { background: #171c19; color: #edf1e9; font-size: 13px; }
QLabel { background: transparent; }
QLabel#muted { color: #96a194; font-size: 12px; }
QLabel#brand { font-size: 25px; font-weight: 650; letter-spacing: 3px; }
QLabel#heading { font-size: 15px; font-weight: 600; }
QLabel#eyebrow { color: #b4d6a4; font-size: 10px; letter-spacing: 2px; }
QFrame#header { border-bottom: 1px solid #30382e; }
QFrame#footer { border-top: 1px solid #30382e; }
QFrame#panel { background: #1d241f; border-radius: 12px; }
QPushButton { background: #2b342c; border: 1px solid #3b463a; border-radius: 7px;
              padding: 9px 14px; font-weight: 500; }
QPushButton:hover { background: #384532; border-color: #6b805e; }
QPushButton:pressed { background: #46563c; }
QPushButton:disabled { color: #727d6e; background: #252c25; border-color: #30382e; }
QPushButton#primary { color: #1a2915; background: #c4e7a5; border-color: #c4e7a5;
                     font-weight: 650; padding: 12px 16px; }
QPushButton#primary:hover { background: #d5f3bd; }
QPushButton#primary:disabled { background: #58694b; color: #a6b39b; border-color: #58694b; }
QPushButton#quiet { border: none; background: transparent; color: #aebba6; padding: 6px 8px; }
QPushButton#quiet:hover { color: #e1f4d1; background: #2a3428; }
QPushButton#mode { padding: 6px 11px; font-size: 12px; background: #222a23; }
QPushButton#mode:checked { background: #405035; border-color: #708361; color: #e3f6d4; }
QListWidget { background: #171c19; border: none; outline: none; }
QListWidget::item { padding: 8px 5px; border-radius: 8px; margin: 3px 0; }
QListWidget::item:selected { background: #34432f; color: #f2f8ed; }
QListWidget::item:hover:!selected { background: #242d24; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #4b5745; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QComboBox { background: #293327; border: 1px solid #46523f; border-radius: 7px;
            padding: 9px 11px; min-height: 17px; }
QComboBox QAbstractItemView { background: #263024; selection-background-color: #46583b; }
QSlider::groove:horizontal { height: 4px; border-radius: 2px; background: #3c4737; }
QSlider::sub-page:horizontal { background: #b6d99a; border-radius: 2px; }
QSlider::handle:horizontal { background: #d1edb5; border: 2px solid #253020;
                           width: 13px; height: 13px; margin: -6px 0; border-radius: 8px; }
QCheckBox { background: transparent; spacing: 7px; color: #bcc7b4; font-size: 12px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #68785a; border-radius: 3px; }
QCheckBox::indicator:checked { background: #bddf9d; border-color: #bddf9d; }
QProgressBar { background: #313b2e; border: none; height: 5px; border-radius: 2px; }
QProgressBar::chunk { background: #c4e7a5; border-radius: 2px; }
QSplitter::handle { background: #30382e; width: 1px; }
QToolTip { color: #eef6e7; background: #34422e; border: 1px solid #60734f; padding: 5px; }
QMenuBar { background: #171c19; }
QMenu { background: #253021; border: 1px solid #46523f; }
QMenu::item:selected { background: #405035; }
"""


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def pil_image(image: Image.Image) -> QImage:
    data = image.tobytes()
    return QImage(data, image.width, image.height, image.width * 3,
                  QImage.Format.Format_RGB888).copy()


def app_icon() -> QIcon:
    pixmap = QPixmap(128, 128)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#253a2a"))
    painter.drawRoundedRect(QRectF(2, 2, 124, 124), 29, 29)
    painter.setBrush(QColor("#d2e9a8"))
    painter.drawEllipse(QRectF(65, 25, 34, 34))
    painter.setBrush(QColor("#74965f"))
    from PySide6.QtGui import QPainterPath
    mountain = QPainterPath()
    mountain.moveTo(16, 98)
    mountain.lineTo(48, 53)
    mountain.lineTo(76, 84)
    mountain.lineTo(94, 67)
    mountain.lineTo(114, 98)
    mountain.closeSubpath()
    painter.drawPath(mountain)
    painter.end()
    return QIcon(pixmap)


class TaskSignals(QObject):
    finished = Signal(object, object, str)
    progress = Signal(int, int, object, str)


class Task(QRunnable):
    def __init__(self, key, function):
        super().__init__()
        self.key = key
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        try:
            result = self.function()
            self.signals.finished.emit(self.key, result, "")
        except Exception as exc:
            self.signals.finished.emit(self.key, None, str(exc) or type(exc).__name__)


class CompareView(QWidget):
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        self.before = None
        self.after = None
        self.ratio = 0.5
        self.mode = "split"
        self.original_only = False
        self.loading = False
        self.error = ""
        self.setMinimumSize(320, 300)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def set_images(self, before, after):
        self.before, self.after = pil_image(before), pil_image(after)
        self.loading = False
        self.error = ""
        self.update()

    def clear(self):
        self.before = self.after = None
        self.loading = False
        self.error = ""
        self.update()

    def fit(self, image, area):
        size = image.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(area.center().x() - size.width() / 2,
                      area.center().y() - size.height() / 2, size.width(), size.height())

    def badge(self, painter, text, x, y):
        painter.setFont(QFont("", 11))
        width = painter.fontMetrics().horizontalAdvance(text) + 22
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 28, 20, 205))
        painter.drawRoundedRect(QRectF(x, y, width, 27), 5, 5)
        painter.setPen(QColor("#eff5e8"))
        painter.drawText(QRectF(x, y, width, 27), Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#101611"))
        area = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        if self.before is None:
            center = area.center()
            painter.setPen(QPen(QColor("#506149"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(center.x() - 58, center.y() - 110, 116, 85)
            painter.drawRoundedRect(box, 12, 12)
            painter.setPen(QPen(QColor("#b9d599"), 2))
            painter.drawEllipse(QRectF(center.x() + 14, center.y() - 94, 17, 17))
            painter.drawLine(int(center.x() - 42), int(center.y() - 43),
                             int(center.x() - 9), int(center.y() - 76))
            painter.drawLine(int(center.x() - 9), int(center.y() - 76),
                             int(center.x() + 24), int(center.y() - 43))
            painter.setPen(QColor("#e4eddc"))
            painter.setFont(QFont("", 23, QFont.Weight.Medium))
            painter.drawText(QRectF(area.x(), center.y(), area.width(), 40),
                             Qt.AlignmentFlag.AlignCenter, "给照片，一点好光线")
            painter.setFont(QFont("", 12))
            painter.setPen(QColor("#8e9d85"))
            message = self.error or ("正在读取照片…" if self.loading else "拖入照片或文件夹，开始批量调色")
            painter.drawText(QRectF(area.x() + 10, center.y() + 51, area.width() - 20, 65),
                             Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, message)
            if not self.loading and not self.error:
                painter.setPen(QColor("#66765d"))
                painter.drawText(QRectF(area.x(), center.y() + 122, area.width(), 25),
                                 Qt.AlignmentFlag.AlignCenter, "JPG  /  JPEG  /  HEIC   ·   全程本地处理")
            painter.end()
            return
        if self.mode == "side" and not self.original_only:
            gap = 10
            half = (area.width() - gap) / 2
            left = QRectF(area.x(), area.y(), half, area.height())
            right = QRectF(area.x() + half + gap, area.y(), half, area.height())
            painter.drawImage(self.fit(self.before, left), self.before)
            painter.drawImage(self.fit(self.after, right), self.after)
            self.badge(painter, "原图", left.x() + 8, area.y() + 8)
            self.badge(painter, "调整后", right.x() + 8, area.y() + 8)
        else:
            target = self.fit(self.before, area)
            painter.drawImage(target, self.before)
            if not self.original_only:
                divider = target.x() + target.width() * self.ratio
                painter.save()
                painter.setClipRect(QRectF(divider, target.y(), target.right() - divider, target.height()))
                painter.drawImage(target, self.after)
                painter.restore()
                painter.setPen(QPen(QColor("#f1f8e9"), 1.5))
                painter.drawLine(int(divider), int(target.top()), int(divider), int(target.bottom()))
                painter.setBrush(QColor("#d0e9b2"))
                painter.setPen(QPen(QColor("#23361c"), 1))
                painter.drawEllipse(QRectF(divider - 16, target.center().y() - 16, 32, 32))
                painter.drawText(QRectF(divider - 15, target.center().y() - 15, 30, 30),
                                 Qt.AlignmentFlag.AlignCenter, "‹  ›")
                self.badge(painter, "原图", target.x() + 10, target.y() + 10)
                self.badge(painter, "调整后", target.right() - 78, target.y() + 10)
            else:
                self.badge(painter, "原图 · 松开空格返回", target.x() + 10, target.y() + 10)
        if self.loading:
            self.badge(painter, "正在更新预览…", area.x() + 10, area.bottom() - 37)
        painter.end()

    def mousePressEvent(self, event):
        if self.before is None and not self.loading:
            self.import_requested.emit()
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if self.before and self.mode == "split" and event.buttons() & Qt.MouseButton.LeftButton:
            target = self.fit(self.before, QRectF(self.rect()).adjusted(18, 18, -18, -18))
            self.ratio = max(0, min(1, (event.position().x() - target.x()) / target.width()))
            self.update()


class AdjustmentSlider(QWidget):
    changed = Signal()

    def __init__(self, title, minimum, maximum, default, formatter=None):
        super().__init__()
        self.formatter = formatter or (lambda value: str(value))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        row = QHBoxLayout()
        row.addWidget(label(title))
        row.addStretch()
        self.value_label = label(self.formatter(default), "muted")
        row.addWidget(self.value_label)
        layout.addLayout(row)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(default)
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.slider.valueChanged.connect(self.on_change)
        layout.addWidget(self.slider)

    def on_change(self, value):
        self.value_label.setText(self.formatter(value))
        self.changed.emit()

    def value(self):
        return self.slider.value() / 100

    def set_value(self, value):
        self.slider.setValue(round(value * 100))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("晴片 · 批量调色")
        self.setWindowIcon(app_icon())
        self.resize(1340, 870)
        self.setMinimumSize(1100, 720)
        self.setAcceptDrops(True)
        self.items = {}
        self.jobs = {}
        self.cache = OrderedDict()
        self.revision = 0
        self.scan_serial = 0
        self.preview_cancel = threading.Event()
        self.export_cancel = threading.Event()
        self.scan_cancel = threading.Event()
        self.exporting = False
        self.scanning = False
        self.output_dir = None
        self.failures = []
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.scan_pool = QThreadPool(self)
        self.scan_pool.setMaxThreadCount(1)
        self.export_pool = QThreadPool(self)
        self.export_pool.setMaxThreadCount(1)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(180)
        self.debounce.timeout.connect(self.request_preview)
        self.build_ui()
        self.build_menu()
        self.update_count()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                and event.key() == Qt.Key.Key_Space
                and isinstance(watched, QWidget)
                and (watched is self or self.isAncestorOf(watched))
                and QApplication.activeModalWidget() is None):
            if not event.isAutoRepeat():
                self.view.original_only = event.type() == QEvent.Type.KeyPress
                self.view.update()
            return True
        return super().eventFilter(watched, event)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 17, 24, 17)
        header_layout.addWidget(label("晴片", "brand"))
        header_layout.addSpacing(13)
        header_layout.addWidget(label("Q I N G P I A N", "eyebrow"))
        header_layout.addStretch()
        header_layout.addWidget(label("一点光线，一点好颜色。", "muted"))
        header_layout.addSpacing(20)
        header_layout.addWidget(label("●  本地处理", "eyebrow"))
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        sidebar = QWidget()
        sidebar.setMinimumWidth(215)
        sidebar.setMaximumWidth(310)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(17, 21, 17, 17)
        side.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.addWidget(label("照片库", "heading"))
        title_row.addStretch()
        self.count_label = label("0 张", "muted")
        title_row.addWidget(self.count_label)
        side.addLayout(title_row)
        self.add_button = button("＋  添加照片", self.choose_files)
        self.add_button.setObjectName("primary")
        side.addWidget(self.add_button)
        self.folder_button = button("导入文件夹", self.choose_folder)
        side.addWidget(self.folder_button)
        self.recursive = QCheckBox("包含子文件夹")
        side.addWidget(self.recursive)
        selection_row = QHBoxLayout()
        self.select_all = QCheckBox("全选")
        self.select_all.setTristate(True)
        self.select_all.clicked.connect(self.toggle_all)
        selection_row.addWidget(self.select_all)
        selection_row.addStretch()
        self.remove_button = button("移除", self.remove_current, "quiet")
        selection_row.addWidget(self.remove_button)
        side.addLayout(selection_row)
        self.photo_list = QListWidget()
        self.photo_list.setIconSize(QSize(46, 46))
        self.photo_list.setSpacing(2)
        self.photo_list.currentItemChanged.connect(self.current_changed)
        self.photo_list.itemChanged.connect(self.update_count)
        side.addWidget(self.photo_list, 1)
        self.library_hint = label("拖入照片或文件夹也可以\n原片始终保留", "muted")
        self.library_hint.setWordWrap(True)
        side.addWidget(self.library_hint)
        splitter.addWidget(sidebar)

        center = QWidget()
        center.setMinimumWidth(480)
        middle = QVBoxLayout(center)
        middle.setContentsMargins(22, 21, 22, 16)
        middle.setSpacing(13)
        modes = QHBoxLayout()
        modes.addWidget(label("效果预览", "heading"))
        modes.addStretch()
        mode_group = QButtonGroup(self)
        for title, mode in (("滑动对比", "split"), ("并排查看", "side")):
            control = button(title, lambda checked=False, selected=mode: self.set_mode(selected), "mode")
            control.setCheckable(True)
            control.setChecked(mode == "split")
            mode_group.addButton(control)
            modes.addWidget(control)
        middle.addLayout(modes)
        self.view = CompareView()
        self.view.import_requested.connect(self.choose_files)
        middle.addWidget(self.view, 1)
        self.file_title = label("等待添加照片", "heading")
        self.file_title.setTextFormat(Qt.TextFormat.PlainText)
        self.file_title.setWordWrap(True)
        middle.addWidget(self.file_title)
        self.photo_info = label("拖动分界线查看前后效果 · 按住空格查看原图", "muted")
        self.photo_info.setWordWrap(True)
        middle.addWidget(self.photo_info)
        splitter.addWidget(center)

        controls = QWidget()
        controls.setMinimumWidth(285)
        controls.setMaximumWidth(335)
        right = QVBoxLayout(controls)
        right.setContentsMargins(18, 21, 21, 18)
        right.setSpacing(13)
        row = QHBoxLayout()
        row.addWidget(label("自动调色", "heading"))
        row.addStretch()
        self.reset_button = button("恢复自动", self.reset, "quiet")
        row.addWidget(self.reset_button)
        right.addLayout(row)
        auto_card = QFrame()
        auto_card.setObjectName("panel")
        auto_layout = QVBoxLayout(auto_card)
        auto_layout.setContentsMargins(14, 15, 14, 15)
        auto_layout.setSpacing(13)
        self.mode_title = label("✓  全自动自然", "eyebrow")
        auto_layout.addWidget(self.mode_title)
        self.mode_hint = label("每张照片，分别适配光线。\n自动平衡明暗与色彩。\n你只需要导入，再批量导出。", "muted")
        self.mode_hint.setWordWrap(True)
        auto_layout.addWidget(self.mode_hint)
        self.scene_summary = label("导入照片后自动分析", "heading")
        self.scene_summary.setWordWrap(True)
        auto_layout.addWidget(self.scene_summary)
        right.addWidget(auto_card)
        self.advanced_toggle = button("高级设置 ▸", self.toggle_advanced, "quiet")
        self.advanced_toggle.setCheckable(True)
        right.addWidget(self.advanced_toggle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 2, 9, 10)
        settings_layout.setSpacing(20)
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.setCurrentText(DEFAULT_PRESET)
        self.preset.currentTextChanged.connect(self.apply_preset)
        settings_layout.addWidget(self.preset)
        self.preset_hint = label(self.preset_description(DEFAULT_PRESET), "muted")
        self.preset_hint.setWordWrap(True)
        settings_layout.addWidget(self.preset_hint)
        self.sliders = {}
        defaults = PRESETS[DEFAULT_PRESET]
        definitions = [
            ("auto", "智能提亮", 0, 100, None),
            ("exposure", "曝光补偿", -100, 150, lambda v: f"{v / 100:+.2f} EV"),
            ("shadows", "暗部细节", 0, 100, None),
            ("highlights", "高光保护", 0, 100, None),
            ("contrast", "对比度", -30, 30, None),
            ("temperature", "色温 · 冷 / 暖", -100, 100, None),
            ("vibrance", "自然鲜艳", -50, 60, None),
            ("intensity", "整体强度", 0, 100, lambda v: f"{v}%"),
        ]
        for key, title, low, high, formatter in definitions:
            slider = AdjustmentSlider(title, low, high, round(getattr(defaults, key) * 100), formatter)
            slider.changed.connect(self.settings_changed)
            slider.setEnabled(not defaults.adaptive)
            self.sliders[key] = slider
            settings_layout.addWidget(slider)
        settings_layout.addStretch()
        scroll.setWidget(settings_widget)
        right.addWidget(scroll, 1)
        self.advanced_scroll = scroll
        scroll.hide()
        self.simple_space = QWidget()
        right.addWidget(self.simple_space, 1)
        self.settings_area = settings_widget
        output_panel = QFrame()
        output_panel.setObjectName("panel")
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(12, 12, 12, 12)
        output_layout.setSpacing(10)
        output_layout.addWidget(label("导出 · 原尺寸 JPG", "eyebrow"))
        output_layout.addWidget(label("原尺寸输出 · 原片始终保留", "muted"))
        self.quality = QComboBox()
        self.quality.addItem("高品质 · 95%", 95)
        self.quality.addItem("最高品质 · 100%", 100)
        self.quality.addItem("节省空间 · 85%", 85)
        output_layout.addWidget(self.quality)
        self.metadata = QCheckBox("保留拍摄信息（含原有定位）")
        self.metadata.setChecked(True)
        output_layout.addWidget(self.metadata)
        self.quality.hide()
        self.metadata.hide()
        self.export_button = button("导出照片", self.start_export, "primary")
        output_layout.addWidget(self.export_button)
        self.cancel_button = button("取消导出", self.cancel_export)
        self.cancel_button.hide()
        output_layout.addWidget(self.cancel_button)
        right.addWidget(output_panel)
        splitter.addWidget(controls)
        splitter.setSizes([235, 790, 315])

        footer = QFrame()
        footer.setObjectName("footer")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(22, 10, 22, 10)
        self.status = label("就绪 · 选择几张照片，让颜色亮起来", "muted")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(150)
        self.progress.hide()
        bottom.addWidget(self.progress)
        self.details_button = button("失败详情", self.show_failures, "quiet")
        self.details_button.hide()
        bottom.addWidget(self.details_button)
        self.open_button = button("打开导出文件夹 ↗", self.open_output, "quiet")
        self.open_button.hide()
        bottom.addWidget(self.open_button)
        layout.addWidget(footer)

    def build_menu(self):
        file_menu = self.menuBar().addMenu("文件")
        for title, shortcut, callback in (
            ("添加照片…", QKeySequence.StandardKey.Open, self.choose_files),
            ("导出勾选照片…", QKeySequence.StandardKey.Save, self.start_export),
            ("移除当前照片", QKeySequence("Backspace"), self.remove_current),
        ):
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("退出晴片", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def submit(self, pool, key, function, progress=None):
        task = Task(key, function)
        task.signals.finished.connect(self.task_finished)
        if progress:
            task.signals.progress.connect(progress)
        self.jobs[key] = task
        pool.start(task)
        return task

    def current_path(self):
        item = self.photo_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def settings(self):
        return Adjustments(**{key: slider.value() for key, slider in self.sliders.items()},
                           adaptive=self.preset.currentText() == DEFAULT_PRESET)

    def toggle_advanced(self, checked):
        self.advanced_scroll.setVisible(checked)
        self.simple_space.setVisible(not checked)
        self.quality.setVisible(checked)
        self.metadata.setVisible(checked)
        self.advanced_toggle.setText("收起高级设置 ▾" if checked else "高级设置 ▸")

    def choose_files(self):
        if self.exporting or self.scanning:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "添加照片", "",
                    "手机照片 (*.jpg *.jpeg *.heic *.heif *.JPG *.JPEG *.HEIC *.HEIF)")
        if files:
            self.add_paths([Path(path) for path in files])

    def choose_folder(self):
        if self.exporting or self.scanning:
            return
        directory = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if directory:
            self.add_paths([Path(directory)])

    def add_paths(self, paths):
        if self.exporting or self.scanning:
            return
        self.scanning = True
        self.scan_cancel = threading.Event()
        self.scan_serial += 1
        recursive = self.recursive.isChecked()
        cancel = self.scan_cancel
        self.set_import_enabled(False)
        self.status.setText("正在扫描照片文件…")
        self.submit(self.scan_pool, ("scan", self.scan_serial),
                    lambda: collect_photos(paths, recursive, cancel))

    def set_import_enabled(self, enabled):
        self.add_button.setEnabled(enabled)
        self.folder_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)

    def current_changed(self, current, previous):
        self.revision += 1
        self.preview_cancel.set()
        self.debounce.stop()
        self.view.clear()
        path = self.current_path()
        self.file_title.setText(path.name if path else "等待添加照片")
        self.photo_info.setText("正在读取照片…" if path else "拖动分界线查看前后效果 · 按住空格查看原图")
        self.scene_summary.setText("正在分析光线与色彩…" if path else "导入照片后自动分析")
        if path:
            self.view.loading = True
            self.view.update()
            self.request_preview()

    def settings_changed(self):
        self.revision += 1
        self.preview_cancel.set()
        if self.current_path():
            self.view.loading = True
            self.view.update()
            self.debounce.start()

    def request_preview(self):
        path = self.current_path()
        if path is None:
            return
        revision = self.revision
        settings = self.settings()
        self.preview_cancel = threading.Event()
        cancel = self.preview_cancel
        # Only the latest request should wait behind the currently running one.
        self.pool.clear()
        for key in list(self.jobs):
            if key[0] == "preview":
                self.jobs.pop(key)
        photo = self.cache.get(path)

        def process():
            if cancel.is_set():
                return None
            loaded = photo or load_photo(path, preview_edge=1600)
            return loaded, adjust_photo(loaded, settings, cancel)

        self.submit(self.pool, ("preview", revision, path), process)

    def task_finished(self, key, result, error):
        self.jobs.pop(key, None)
        kind = key[0]
        if kind == "scan":
            self.scanning = False
            self.set_import_enabled(not self.exporting)
            if error:
                self.status.setText("导入失败")
                QMessageBox.warning(self, "无法导入", error)
                return
            added = 0
            first = None
            self.photo_list.blockSignals(True)
            for path in result:
                if path in self.items:
                    continue
                item = QListWidgetItem(f"{path.name}\n{path.suffix[1:].upper()}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setToolTip(str(path))
                item.setCheckState(Qt.CheckState.Checked)
                item.setSizeHint(QSize(150, 65))
                self.photo_list.addItem(item)
                self.items[path] = item
                first = first or item
                added += 1
            self.photo_list.blockSignals(False)
            if self.photo_list.currentItem() is None and first:
                self.photo_list.setCurrentItem(first)
            self.status.setText(f"已添加 {added} 张照片 · 勾选照片后可批量导出" if added else
                                "没有新增照片 · 支持 JPG、JPEG、HEIC，重复照片会自动跳过")
            self.update_count()
        elif kind == "preview":
            if key[1] != self.revision or key[2] != self.current_path():
                return
            self.view.loading = False
            if error or result is None:
                self.view.clear()
                self.view.error = error or "预览已取消"
                self.view.update()
                self.photo_info.setText("读取失败：" + self.view.error)
                self.scene_summary.setText("此照片暂时无法读取")
                return
            photo, edited = result
            self.cache[key[2]] = photo
            self.cache.move_to_end(key[2])
            while len(self.cache) > 3:
                self.cache.popitem(last=False)
            self.view.set_images(photo.image, edited)
            if self.settings().adaptive:
                description = photo.auto_plan.description
                self.scene_summary.setText(description)
            else:
                description = self.preset.currentText()
                self.scene_summary.setText("按所选预设调色")
            self.photo_info.setText(f"{photo.size[0]} × {photo.size[1]} px  ·  "
                                   f"{description}  ·  导出保留原尺寸")
            thumbnail = photo.image.copy()
            thumbnail.thumbnail((92, 92), Image.Resampling.LANCZOS)
            item = self.items.get(key[2])
            if item:
                item.setIcon(QIcon(QPixmap.fromImage(pil_image(thumbnail))))
        elif kind == "export":
            self.finish_export(result, error)

    def update_count(self, *args):
        total = len(self.items)
        selected = sum(item.checkState() == Qt.CheckState.Checked for item in self.items.values())
        self.count_label.setText(f"{total} 张")
        self.export_button.setText(f"批量导出 · {selected} 张")
        self.export_button.setEnabled(bool(selected) and not self.exporting and not self.scanning)
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(Qt.CheckState.Unchecked if not selected else
                                     Qt.CheckState.Checked if selected == total else Qt.CheckState.PartiallyChecked)
        self.select_all.blockSignals(False)

    def toggle_all(self):
        # A mixed selection is promoted to all selected, then toggles normally.
        selected = sum(item.checkState() == Qt.CheckState.Checked for item in self.items.values())
        state = Qt.CheckState.Unchecked if selected == len(self.items) else Qt.CheckState.Checked
        self.photo_list.blockSignals(True)
        for item in self.items.values():
            item.setCheckState(state)
        self.photo_list.blockSignals(False)
        self.update_count()

    def remove_current(self):
        if self.exporting or self.scanning:
            return
        path = self.current_path()
        if path is None:
            return
        item = self.items.pop(path)
        self.photo_list.takeItem(self.photo_list.row(item))
        self.cache.pop(path, None)
        self.update_count()

    def set_mode(self, mode):
        self.view.mode = mode
        self.view.update()

    def preset_description(self, name):
        if name == DEFAULT_PRESET:
            return ("全自动逐张处理，无需调参数。\n"
                    "曝光、暗部、高光、色彩分别适配。\n"
                    "下方数值用于其他预设，自动模式无需设置。")
        if name == "影楼自然光":
            return ("推荐日常人像和生活照，逐张适配亮度。\n"
                    "柔和提亮、控制鲜艳度，保留原有色温。\n"
                    "不熟悉参数，保持默认即可。")
        return "同一组参数，逐张适配亮度。\n以下设置会应用到所有勾选的照片。"

    def apply_preset(self, name):
        settings = PRESETS[name]
        self.preset_hint.setText(self.preset_description(name))
        self.mode_title.setText("✓  全自动自然" if settings.adaptive else name)
        self.mode_hint.setText("每张照片，分别适配光线。\n自动平衡明暗与色彩。\n你只需要导入，再批量导出。"
                               if settings.adaptive else "按预设处理，可在高级设置中微调。\n点击“恢复自动”即可回到全自动模式。")
        for key, slider in self.sliders.items():
            slider.set_value(getattr(settings, key))
            slider.setEnabled(not settings.adaptive)
        self.settings_changed()

    def reset(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentText(DEFAULT_PRESET)
        self.preset.blockSignals(False)
        self.apply_preset(DEFAULT_PRESET)

    def start_export(self):
        if self.exporting or self.scanning:
            return
        paths = [path for path, item in self.items.items() if item.checkState() == Qt.CheckState.Checked]
        if not paths:
            return
        directory = QFileDialog.getExistingDirectory(self, "选择导出位置（会新建“晴片导出”子文件夹）",
                                                     str(paths[0].parent))
        if not directory:
            return
        self.begin_export(paths, Path(directory) / "晴片导出")

    def begin_export(self, paths, output_dir):
        self.output_dir = Path(output_dir)
        self.exporting = True
        self.failures = []
        self.export_cancel = threading.Event()
        cancel = self.export_cancel
        settings = self.settings()
        quality, metadata = self.quality.currentData(), self.metadata.isChecked()
        self.set_import_enabled(False)
        self.settings_area.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.photo_list.setEnabled(False)
        self.preset.setEnabled(False)
        self.quality.setEnabled(False)
        self.metadata.setEnabled(False)
        self.select_all.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.export_button.setEnabled(False)
        self.open_button.hide()
        self.details_button.hide()
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText(f"正在导出 0 / {len(paths)} · 正在读取第一张照片…")
        task = Task(("export",), lambda: None)
        task.function = lambda: export_batch(paths, self.output_dir, settings, quality,
                            metadata, cancel, task.signals.progress.emit)
        task.signals.finished.connect(self.task_finished)
        task.signals.progress.connect(self.export_progress)
        self.jobs[task.key] = task
        self.export_pool.start(task)

    def export_progress(self, completed, total, path, error):
        self.progress.setValue(completed)
        state = "跳过失败照片" if error else "已保存"
        self.status.setText(f"{state} {completed} / {total} · {path.name}")

    def cancel_export(self):
        self.export_cancel.set()
        self.cancel_button.setEnabled(False)
        self.status.setText("正在取消… 已导出的照片会保留")

    def finish_export(self, result, error):
        self.exporting = False
        self.set_import_enabled(True)
        for widget in (self.settings_area, self.photo_list, self.preset, self.quality,
                       self.metadata, self.select_all, self.reset_button):
            widget.setEnabled(True)
        self.cancel_button.hide()
        self.progress.hide()
        self.update_count()
        if error:
            self.status.setText("导出遇到问题")
            QMessageBox.warning(self, "导出失败", error)
            return
        successes, self.failures = result
        prefix = "已取消" if self.export_cancel.is_set() else "导出完成"
        self.status.setText(f"{prefix} · 成功 {len(successes)} 张，失败 {len(self.failures)} 张")
        self.open_button.setVisible(bool(successes))
        self.details_button.setVisible(bool(self.failures))

    def show_failures(self):
        message = QMessageBox(self)
        message.setWindowTitle("未能导出的照片")
        message.setText(f"{len(self.failures)} 张照片未导出，其他照片已继续处理。")
        message.setDetailedText("\n\n".join(f"{path}\n{error}" for path, error in self.failures))
        message.exec()

    def open_output(self):
        if self.output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.exporting and not self.scanning:
            if any(url.isLocalFile() for url in event.mimeData().urls()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.add_paths(paths)
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.view.original_only = True
            self.view.update()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.view.original_only = False
            self.view.update()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if hasattr(self, "view"):
                self.view.original_only = False
                self.view.update()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.exporting:
            choice = QMessageBox.question(self, "正在导出", "停止导出并退出？已导出的照片会保留。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.debounce.stop()
        self.preview_cancel.set()
        self.export_cancel.set()
        self.scan_cancel.set()
        self.pool.clear()
        self.scan_pool.clear()
        # Running workers may still be encoding. Keep the Qt event loop alive
        # until they stop, without deleting any signal receivers prematurely.
        if any(pool.activeThreadCount() for pool in (self.pool, self.scan_pool, self.export_pool)):
            self.hide()
            self._closing = QTimer(self)
            self._closing.timeout.connect(self.quit_when_idle)
            self._closing.start(80)
            event.ignore()
        else:
            event.accept()

    def quit_when_idle(self):
        if not any(pool.activeThreadCount() for pool in (self.pool, self.scan_pool, self.export_pool)):
            QApplication.instance().quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("晴片")
    app.setOrganizationName("Qingpian")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        paths = [Path(value) for value in sys.argv[1:] if not value.startswith("-psn_")]
        if paths:
            QTimer.singleShot(0, lambda: window.add_paths(paths))
    sys.exit(app.exec())
