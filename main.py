"""DHU 抢课助手 —— 单一入口 Qt 应用

Ver3.1：
  * 三标签：配置 / 选课 / 抢课
  * 配置页：账号信息 + 代理设置
  * 选课页：点「开始运行」登录并抓取当前已选课程与总学分（只读展示，含刷新、查看课程表）
  * 抢课页：循环设置 + 激活模式 + 任务列表 + 实时监控 + 抢课控制
  * 无 Flask / 无 SSE / 无 Tkinter / 无控制台模式

运行：python main.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStyleFactory,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import api
import parser as p
import state
from auth import login
from loader import load_config
from strategies import RestartRequired, run_task

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

MAX_RELOGIN_ATTEMPTS = 5

# 学期显示名 → term_id 映射，20262027a=88 起，每学期+1，a=秋，s=春
TERMS: dict[str, int] = {}
_tid = 88
for _y in range(2026, 2034):
    TERMS[f"{_y}{_y + 1}a"] = _tid
    _tid += 1
    TERMS[f"{_y}{_y + 1}s"] = _tid
    _tid += 1
TERM_LABELS = list(TERMS.keys())
TERM_BY_ID = {v: k for k, v in TERMS.items()}

MODES = [
    ("Only_Submit", "直接抢课 (Only_Submit)", "不查名额，直接并发提交"),
    ("FQTS", "查询后抢课 (FQTS)", "先查名额，有余量再提交"),
    ("FQTDLS", "调课模式 (FQTDLS)", "退旧课后选新课，失败自动回滚"),
]
MODE_VALUES = [m[0] for m in MODES]
QUERY_MODES = {"FQTS", "FQTDLS"}
MODE_LABELS = {value: label for value, label, _desc in MODES}

TASK_COLUMNS = [
    ("mode", "模式", 130),
    ("main_id", "课程代码", 100),
    ("target_ids", "目标教学班ID", 200),
    ("del_class_no", "退课班号", 100),
    ("del_raw_id", "回滚ID", 100),
]

COURSE_COLUMNS = [
    ("code", "课程代码", 100),
    ("name", "课程名称", 240),
    ("credit", "学分", 70),
    ("category", "课程类别", 120),
    ("class_no", "组班", 70),
    ("teacher", "任课教师", 130),
]

# 节次 → 时间（松江校区和延安路校区）
PERIODS = [
    ("第一节", "8:15-9:00"), ("第二节", "9:00-9:45"),
    ("第三节", "10:05-10:50"), ("第四节", "10:50-11:35"),
    ("第五节", "13:00-13:45"), ("第六节", "13:45-14:30"),
    ("第七节", "14:50-15:35"), ("第八节", "15:35-16:20"),
    ("第九节", "16:20-17:05"),
    ("第十节", "18:00-18:45"), ("第十一节", "18:45-19:30"),
    ("第十二节", "19:50-20:35"), ("第十三节", "20:35-21:20"),
]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CELL_COLORS = ["#dbeafe", "#dcfce7", "#fef3c7", "#fae8ff", "#ffe4e6", "#cffafe",
               "#e0e7ff", "#fef9c3", "#d1fae5", "#fee2e2", "#e9d5ff", "#ccfbf1"]

STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "waiting": "等待确认",
    "success": "成功",
    "error": "异常",
    "blocked": "已阻塞",
}
STATUS_COLORS = {
    "idle": "#5f6368",
    "running": "#9d5d00",
    "waiting": "#0067c0",
    "success": "#107c10",
    "error": "#c42b1c",
    "blocked": "#c42b1c",
}
LOG_COLORS = {
    "info": "#202124",
    "success": "#107c10",
    "warn": "#9d5d00",
    "error": "#c42b1c",
}

PRIMARY_BUTTON_QSS = """
QPushButton {
    background-color: #0067c0;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 9px 22px;
    font-weight: 600;
}
QPushButton:hover { background-color: #1877c9; }
QPushButton:pressed { background-color: #005ba4; }
QPushButton:disabled { background-color: #c8c8c8; color: #f2f2f2; }
"""


def apply_theme(app: QApplication) -> None:
    """Windows 11 原生样式 + 强制浅色配色；不设置全局 QSS。"""
    available = set(QStyleFactory.keys())
    for name in ("windows11", "windowsvista"):
        if name in available:
            app.setStyle(name)
            break
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setFont(QFont("Microsoft YaHei UI", 10))


def _hint(text: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text)
    pal = label.palette()
    pal.setColor(QPalette.ColorRole.WindowText, pal.color(QPalette.ColorRole.PlaceholderText))
    label.setPalette(pal)
    font = QFont(label.font())
    size = font.pointSizeF()
    if size > 0:
        font.setPointSizeF(max(8.0, size - 1.0))
    label.setFont(font)
    label.setWordWrap(wrap)
    return label


def _set_color(label: QLabel, color: str | None) -> None:
    label.setStyleSheet(f"color: {color}; background: transparent;" if color else "")


def _big(label: QLabel, delta: float = 2.0, bold: bool = True) -> QLabel:
    font = QFont(label.font())
    size = font.pointSizeF()
    if size > 0:
        font.setPointSizeF(size + delta)
    font.setBold(bold)
    label.setFont(font)
    return label


def semester_label(semester: str) -> str:
    """'20262027a' -> '2026-2027学年 第 1 学期'"""
    if len(semester) >= 9 and semester[:8].isdigit():
        return f"{semester[:4]}-{semester[4:8]}学年 第 {1 if semester[8] == 'a' else 2} 学期"
    return semester or "—"


# =============================================================================
# 配置页：账号信息 + 代理设置
# =============================================================================
class ConfigPage(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._dirty = False
        self._loading = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_credentials(), 3)
        body.addWidget(self._build_proxy(), 2)
        root.addLayout(body)
        root.addStretch(1)

    def _build_credentials(self) -> QGroupBox:
        box = QGroupBox("账号信息")
        form = QFormLayout(box)
        form.setContentsMargins(14, 16, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("学号")
        self.username_edit.setMinimumHeight(32)
        self.username_edit.textChanged.connect(self._mark_dirty)

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("密码")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumHeight(32)
        self.password_edit.textChanged.connect(self._mark_dirty)

        term_row = QHBoxLayout()
        term_row.setSpacing(8)
        self.term_combo = QComboBox()
        self.term_combo.addItems(TERM_LABELS)
        self.term_combo.setMinimumHeight(32)
        self.term_combo.currentTextChanged.connect(self._update_term_hint)
        self.term_combo.currentIndexChanged.connect(self._mark_dirty)
        self.term_id_label = _hint("")
        term_row.addWidget(self.term_combo, 1)
        term_row.addWidget(self.term_id_label)

        form.addRow("学号", self.username_edit)
        form.addRow("密码", self.password_edit)
        form.addRow("学期", term_row)
        return box

    def _build_proxy(self) -> QGroupBox:
        box = QGroupBox("代理设置")
        form = QFormLayout(box)
        form.setContentsMargins(14, 16, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.proxy_enabled = QCheckBox("启用代理")
        self.proxy_enabled.toggled.connect(self._sync_proxy_enabled)
        self.proxy_enabled.toggled.connect(self._mark_dirty)

        self.proxy_host = QLineEdit("localhost")
        self.proxy_host.setMinimumHeight(32)
        self.proxy_host.textChanged.connect(self._mark_dirty)

        self.proxy_port = QLineEdit("8888")
        self.proxy_port.setMinimumHeight(32)
        self.proxy_port.setMaximumWidth(96)
        self.proxy_port.textChanged.connect(self._mark_dirty)

        form.addRow(self.proxy_enabled)
        form.addRow("代理地址", self.proxy_host)
        form.addRow("端口", self.proxy_port)
        return box

    # ---------------- 脏标记 ----------------
    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)

    def _clear_dirty(self) -> None:
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)

    def is_dirty(self) -> bool:
        return self._dirty

    def _update_term_hint(self) -> None:
        self.term_id_label.setText(f"term_id={TERMS.get(self.term_combo.currentText(), 86)}")

    def _sync_proxy_enabled(self, checked: bool) -> None:
        self.proxy_host.setEnabled(checked)
        self.proxy_port.setEnabled(checked)

    # ---------------- 数据 ----------------
    def load(self, data: dict) -> None:
        self._loading = True
        try:
            self.username_edit.setText(data.get("username", ""))
            self.password_edit.setText(data.get("password", ""))
            self.term_combo.setCurrentText(TERM_BY_ID.get(data.get("term_id", 86), TERM_LABELS[0]))
            proxy = data.get("proxy") or {}
            self.proxy_enabled.setChecked(proxy.get("enabled", True))
            self.proxy_host.setText(proxy.get("host", "localhost"))
            self.proxy_port.setText(str(proxy.get("port", 8888)))
        finally:
            self._loading = False
        self._update_term_hint()
        self._sync_proxy_enabled(self.proxy_enabled.isChecked())
        self._clear_dirty()

    def values(self) -> dict:
        return {
            "username": self.username_edit.text().strip(),
            "password": self.password_edit.text(),
            "term_id": TERMS.get(self.term_combo.currentText(), 86),
            "proxy": {
                "enabled": self.proxy_enabled.isChecked(),
                "host": self.proxy_host.text().strip(),
                "port": int(self.proxy_port.text().strip() or 8888),
            },
        }


# =============================================================================
# 任务编辑对话框
# =============================================================================
class TaskDialog(QDialog):
    FIELDS = [
        ("main_id", "课程代码 (mainID)", "FQTS / FQTDLS 必填"),
        ("target_ids", "目标教学班ID", "多个用逗号分隔"),
        ("del_class_no", "退课班号 (classNo)", "FQTDLS 模式必填"),
        ("del_raw_id", "回滚ID (Raw)", "FQTDLS 模式必填"),
    ]

    def __init__(self, parent=None, mode: str = "Only_Submit", existing: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑任务" if existing else "添加任务")
        self.setModal(True)
        self.setMinimumWidth(600)
        data = existing or {}
        self._task: dict | None = None

        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumHeight(32)
        for value, label, _desc in MODES:
            self.mode_combo.addItem(label, value)
        current = data.get("mode", mode)
        self.mode_combo.setCurrentIndex(MODE_VALUES.index(current) if current in MODE_VALUES else 0)
        form.addRow("模式", self.mode_combo)

        self.edits: dict[str, QLineEdit] = {}
        for key, label, hint in self.FIELDS:
            value = ", ".join(data.get(key) or []) if key == "target_ids" else data.get(key, "")
            edit = QLineEdit(value)
            edit.setMinimumHeight(32)
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(edit, 1)
            row.addWidget(_hint(hint))
            self.edits[key] = edit
            form.addRow(label, row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("确定")
        ok_btn.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _confirm(self) -> None:
        raw_ids = [x.strip() for x in self.edits["target_ids"].text().split(",") if x.strip()]
        if not raw_ids:
            QMessageBox.showerror("错误", "目标教学班ID不能为空", parent=self)
            return
        self._task = {
            "mode": self.mode_combo.currentData(),
            "main_id": self.edits["main_id"].text().strip(),
            "target_ids": raw_ids,
            "del_class_no": self.edits["del_class_no"].text().strip(),
            "del_raw_id": self.edits["del_raw_id"].text().strip(),
        }
        self.accept()

    def result_task(self) -> dict | None:
        return self._task


# =============================================================================
# 抢课页：循环设置 + 激活模式 + 任务列表 + 实时监控 + 控制
# =============================================================================
class GrabPage(QWidget):
    dirty_changed = Signal(bool)
    start_requested = Signal()
    stop_requested = Signal()
    continue_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tasks: list[dict] = []
        self._dirty = False
        self._loading = False
        self._last_log_id = 0
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self._build_loop())
        left.addWidget(self._build_modes())
        left.addStretch(1)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(400)
        top.addWidget(left_wrap)
        top.addWidget(self._build_task_list(), 1)
        root.addLayout(top, 3)

        root.addLayout(self._build_cards())

        log_box = QGroupBox("实时日志")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(14, 16, 14, 14)
        self.log_list = QListWidget()
        self.log_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.log_list.setUniformItemSizes(True)
        font = QFont(self.log_list.font())
        size = font.pointSizeF()
        if size > 0:
            font.setPointSizeF(max(8.0, size - 0.5))
        self.log_list.setFont(font)
        log_layout.addWidget(self.log_list)
        root.addWidget(log_box, 2)

        bar = QHBoxLayout()
        bar.addStretch(1)
        self.continue_btn = QPushButton("继续下一轮")
        self.start_btn = QPushButton("开始抢课")
        self.start_btn.setStyleSheet(PRIMARY_BUTTON_QSS)
        self.stop_btn = QPushButton("停止")
        for btn, width in ((self.continue_btn, 120), (self.start_btn, 150), (self.stop_btn, 100)):
            btn.setMinimumHeight(38)
            btn.setMinimumWidth(width)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(btn)
        self.continue_btn.clicked.connect(self.continue_requested.emit)
        self.start_btn.clicked.connect(self.start_requested.emit)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        root.addLayout(bar)

    def _build_loop(self) -> QGroupBox:
        box = QGroupBox("循环设置")
        form = QFormLayout(box)
        form.setContentsMargins(14, 16, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.interval_edit = QLineEdit("3")
        self.interval_edit.setMinimumHeight(32)
        self.interval_edit.setMaximumWidth(90)
        self.interval_edit.textChanged.connect(self._mark_dirty)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.interval_edit)
        row.addWidget(_hint("秒（FQTS / FQTDLS 生效）", wrap=False))
        row.addStretch(1)
        form.addRow("轮询间隔", row)
        return box

    def _build_modes(self) -> QGroupBox:
        box = QGroupBox("激活模式")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 16, 14, 14)
        v.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        for i, (_value, label, _desc) in enumerate(MODES):
            rb = QRadioButton(label)
            rb.setMinimumHeight(26)
            rb.setChecked(i == 0)
            self.mode_group.addButton(rb, i)
            v.addWidget(rb)
        self.mode_group.buttonToggled.connect(self._on_mode_toggled)
        self.mode_desc = _hint("")
        v.addSpacing(2)
        v.addWidget(self.mode_desc)
        v.addStretch(1)
        return box

    def _build_task_list(self) -> QGroupBox:
        box = QGroupBox("任务列表")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 16, 14, 14)
        v.setSpacing(10)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for text, slot in (("添加任务", self._add_task),
                           ("编辑选中", self._edit_task),
                           ("删除选中", self._del_task)):
            btn = QPushButton(text)
            btn.setMinimumHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        v.addLayout(toolbar)

        self.table = QTableWidget(0, len(TASK_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in TASK_COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        for i, (_key, _title, width) in enumerate(TASK_COLUMNS):
            self.table.setColumnWidth(i, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._edit_task)
        v.addWidget(self.table)
        return box

    def _build_cards(self) -> QHBoxLayout:
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_mode, self.value_mode = self._make_card("激活模式")
        self.card_status, self.value_status = self._make_card("当前状态")
        self.card_result, self.value_result = self._make_card("选课结果")
        self.card_round, self.value_round = self._make_card("已完成轮次")
        self.card_query, self.value_query = self._make_card("查询次数")
        for card in (self.card_mode, self.card_status, self.card_result,
                     self.card_round, self.card_query):
            cards.addWidget(card, 1)
        return cards

    def _make_card(self, title: str) -> tuple[QGroupBox, QLabel]:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 16, 12, 12)
        value = _big(QLabel("—"))
        v.addWidget(value)
        return box, value

    # ---------------- 脏标记 ----------------
    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)

    def _clear_dirty(self) -> None:
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)

    def is_dirty(self) -> bool:
        return self._dirty

    # ---------------- 模式 ----------------
    def _current_mode(self) -> str:
        idx = self.mode_group.checkedId()
        return MODE_VALUES[idx] if 0 <= idx < len(MODE_VALUES) else MODE_VALUES[0]

    def _set_mode(self, mode: str) -> None:
        idx = MODE_VALUES.index(mode) if mode in MODE_VALUES else 0
        button = self.mode_group.button(idx)
        if button is not None:
            button.setChecked(True)

    def _on_mode_toggled(self, _button, checked: bool) -> None:
        if checked:
            self._on_mode_changed()
            self._mark_dirty()

    def _on_mode_changed(self) -> None:
        current = self._current_mode()
        for value, _label, desc in MODES:
            if value == current:
                self.mode_desc.setText(desc)
                break

    # ---------------- 任务 ----------------
    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.tasks))
        for r, t in enumerate(self.tasks):
            values = [
                t.get("mode", ""),
                t.get("main_id", ""),
                ", ".join(t.get("target_ids") or []),
                t.get("del_class_no", ""),
                t.get("del_raw_id", ""),
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, c, item)

    def _add_task(self) -> None:
        dlg = TaskDialog(self, self._current_mode())
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_task():
            self.tasks.append(dlg.result_task())
            self._refresh_table()
            self._mark_dirty()

    def _edit_task(self, *_args) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.tasks):
            return
        current = self.tasks[row]
        dlg = TaskDialog(self, current.get("mode", self._current_mode()), existing=current)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_task():
            self.tasks[row] = dlg.result_task()
            self._refresh_table()
            self._mark_dirty()

    def _del_task(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中一行任务。")
            return
        self.tasks.pop(row)
        self._refresh_table()
        self._mark_dirty()

    # ---------------- 数据 ----------------
    def load(self, data: dict) -> None:
        self._loading = True
        try:
            self._set_mode(data.get("active_mode", "Only_Submit"))
            self.interval_edit.setText(str(data.get("loop_interval", 3)))
            self.tasks = data.get("tasks") or []
        finally:
            self._loading = False
        self._on_mode_changed()
        self._refresh_table()
        self._clear_dirty()

    def values(self) -> dict:
        return {
            "active_mode": self._current_mode(),
            "loop_interval": float(self.interval_edit.text().strip() or 3),
            "tasks": self.tasks,
        }

    # ---------------- 监控 ----------------
    def clear_logs(self) -> None:
        self.log_list.clear()
        self._last_log_id = 0

    def refresh(self, snap: dict) -> None:
        mode = snap.get("active_mode") or ""
        self.value_mode.setText(MODE_LABELS.get(mode, mode or "—"))

        status = snap.get("status", "idle")
        self.value_status.setText(STATUS_LABELS.get(status, status))
        _set_color(self.value_status, STATUS_COLORS.get(status, "#202124"))

        success = bool(snap.get("success"))
        if success:
            text, color = "✓ 选课成功", STATUS_COLORS["success"]
        elif status in ("running", "waiting"):
            text, color = "进行中…", STATUS_COLORS["running"]
        elif status in ("error", "blocked"):
            text, color = "未成功", STATUS_COLORS["error"]
        else:
            text, color = "—", None
        self.value_result.setText(text)
        _set_color(self.value_result, color)

        self.value_round.setText(str(snap.get("round", 0)))
        self.value_query.setText(str(snap.get("query_count", 0)))
        self.card_query.setVisible(mode in QUERY_MODES)

        added = False
        for entry in snap.get("logs", []):
            entry_id = entry.get("id", 0)
            if entry_id <= self._last_log_id:
                continue
            self._last_log_id = entry_id
            item = QListWidgetItem(f'{entry.get("time", "")}  {entry.get("msg", "")}')
            item.setForeground(QColor(LOG_COLORS.get(entry.get("level", "info"), "#202124")))
            self.log_list.addItem(item)
            added = True
            if self.log_list.count() > 400:
                self.log_list.takeItem(0)
        if added:
            self.log_list.scrollToBottom()


# =============================================================================
# 选课页：当前已选课程 + 课程表（只读展示）
# =============================================================================
class CoursePage(QWidget):
    refresh_requested = Signal()
    timetable_requested = Signal()
    pending_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._build()
        self.update_from_state(state.get_state())

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(16)
        info = QVBoxLayout()
        info.setSpacing(2)
        self.semester_label = _hint("选课学期：—")
        self.total_label = _big(QLabel("当前已选课程总学分：—"), 4.0)
        info.addWidget(self.semester_label)
        info.addWidget(self.total_label)
        head.addLayout(info)
        head.addStretch(1)

        self.timetable_btn = QPushButton("查看当前课程表")
        self.timetable_btn.setMinimumHeight(38)
        self.timetable_btn.setMinimumWidth(160)
        self.timetable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.timetable_btn.setStyleSheet(PRIMARY_BUTTON_QSS)
        self.timetable_btn.clicked.connect(self.timetable_requested.emit)
        head.addWidget(self.timetable_btn)

        self.pending_btn = QPushButton("查看应读未读课程")
        self.pending_btn.setMinimumHeight(38)
        self.pending_btn.setMinimumWidth(170)
        self.pending_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pending_btn.setStyleSheet(PRIMARY_BUTTON_QSS)
        self.pending_btn.clicked.connect(self.pending_requested.emit)
        head.addWidget(self.pending_btn)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setMinimumHeight(38)
        self.refresh_btn.setMinimumWidth(100)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        self.status_label = _hint("")
        root.addWidget(self.status_label)

        box = QGroupBox("当前已选课程")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 16, 14, 14)
        self.table = QTableWidget(0, len(COURSE_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COURSE_COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        for i, (_key, _title, width) in enumerate(COURSE_COLUMNS):
            self.table.setColumnWidth(i, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.table)
        root.addWidget(box, 1)

    def update_from_state(self, snap: dict) -> None:
        pending = snap.get("pending") or {}
        self.pending_btn.setEnabled(bool(pending.get("groups")))
        rec = snap.get("selected")
        if not rec:
            self.semester_label.setText("选课学期：—")
            self.total_label.setText("当前已选课程总学分：—")
            self.status_label.setText("点击「开始运行」登录并获取当前已选课程。")
            self.table.setRowCount(0)
            self.timetable_btn.setEnabled(False)
            return

        status = rec.get("status")
        if status == "loading":
            self.status_label.setText("正在获取…")
            self.timetable_btn.setEnabled(False)
            return
        if status == "error":
            self.status_label.setText("获取失败：" + str(rec.get("error", "")))
            self.timetable_btn.setEnabled(False)
            return

        semester = rec.get("semester", "")
        self.semester_label.setText(
            f"选课学期：{rec.get('semester_label') or semester_label(semester)}"
            f"　｜　获取时间：{rec.get('fetched_at', '—')}")
        self.total_label.setText(f"当前已选课程总学分：{rec.get('report_credit', rec.get('total_credit', 0))}")

        courses = rec.get("courses") or []
        self.table.setRowCount(len(courses))
        for r, c in enumerate(courses):
            cells = [c.get("code", ""), c.get("name", ""),
                     f"{float(c.get('credit', 0)):g}", c.get("category", ""),
                     c.get("class_no", ""), c.get("teacher", "")]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(r, col, item)
        conflicts = [c["name"] for c in courses if c.get("conflict")]
        note = f"共 {len(courses)} 门课程。"
        if conflicts:
            note += "　⚠ 时间冲突：" + "、".join(conflicts)
        self.status_label.setText(note)
        self.timetable_btn.setEnabled(bool(courses))



# =============================================================================
# 课程表对话框：13 节 × 7 天
# =============================================================================
class TimetableDialog(QDialog):
    def __init__(self, parent=None, selected: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("当前课程表")
        self.setModal(True)
        selected = selected or {}
        courses = selected.get("courses") or []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel(f"共 {len(courses)} 门课　｜　总学分 "
                       f"{selected.get('report_credit', selected.get('total_credit', 0))}")
        _big(title, 1.0)
        root.addWidget(title)

        # 展开到 (节次, 星期) 格子；同一门课一种底色
        grid: dict = {}
        color_of: dict = {}
        for i, c in enumerate(courses):
            color_of[c["code"]] = CELL_COLORS[i % len(CELL_COLORS)]
            for slot in c.get("slots") or []:
                for day, period in slot.get("periods") or []:
                    grid.setdefault((period, day), []).append((c, slot))

        table = QTableWidget(len(PERIODS), len(WEEKDAYS) + 1)
        table.setHorizontalHeaderLabels(["节次"] + WEEKDAYS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setWordWrap(True)
        table.setAlternatingRowColors(False)
        table.horizontalHeader().setHighlightSections(False)
        cell_font = QFont(table.font())
        cell_size = cell_font.pointSizeF()
        if cell_size > 0:
            cell_font.setPointSizeF(max(8.0, cell_size - 0.5))
        table.setFont(cell_font)

        for r, (name, span) in enumerate(PERIODS):
            item = QTableWidgetItem(f"{name}\n{span}")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(r, 0, item)
            table.setRowHeight(r, 66)

        for (period, day), entries in grid.items():
            blocks = []
            for c, slot in entries:
                lines = [c["name"]]
                tail = " ".join(x for x in (slot.get("weeks"), slot.get("room")) if x)
                if tail:
                    lines.append(tail)
                blocks.append("\n".join(lines))
            item = QTableWidgetItem("\n\n".join(blocks))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = color_of.get(entries[0][0]["code"])
            if color:
                item.setBackground(QColor(color))
            table.setItem(period - 1, day + 1, item)

        table.setColumnWidth(0, 110)
        for col in range(1, len(WEEKDAYS) + 1):
            table.setColumnWidth(col, 152)
        root.addWidget(table, 1)

        no_time = [c["name"] for c in courses if not c.get("slots")]
        note = "实习/实践类课程没有固定上课时间，不显示在表中。"
        if no_time:
            note = "无固定上课时间：" + "、".join(no_time)
        root.addWidget(_hint(note))

        bar = QHBoxLayout()
        bar.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(34)
        close_btn.setMinimumWidth(110)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        root.addLayout(bar)

        self.resize(1280, 880)


class PendingCoursesDialog(QDialog):
    """培养方案中应读但尚未修读的课程，按课程类别分组。"""

    def __init__(self, parent=None, pending: dict | None = None,
                 selected_codes=None, fetcher=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("应读未读课程")
        self.setModal(True)
        pending = pending or {}
        groups = pending.get("groups") or []
        selected_codes = {str(x) for x in (selected_codes or [])}
        self._fetcher = fetcher
        self._term_id = pending.get("term_id")
        self._semester_label = pending.get("semester_label", "")
        self._row_courses: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        sel_count = sum(1 for g in groups for c in (g.get("courses") or [])
                        if str(c.get("code")) in selected_codes)
        title = QLabel(f"共 {pending.get('count', 0)} 门未读课程　｜　"
                       f"合计 {pending.get('total_credit', 0)} 学分"
                       + (f"　｜　其中 {sel_count} 门本学期已选（黄色）" if sel_count else ""))
        _big(title, 1.0)
        root.addWidget(title)
        root.addWidget(_hint("提示：双击任意课程，查看该课程本学期的开课情况（所有教学班与上课时间）。"))

        columns = ["课程代码", "课程名称", "学分", "计划学期", "状态"]
        rows: list = []
        for g in groups:
            rows.append(("group", g))
            for c in g.get("courses") or []:
                rows.append(("course", c))

        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)

        for r, (kind, obj) in enumerate(rows):
            if kind == "group":
                table.setSpan(r, 0, 1, len(columns))
                text = f"{obj['category']}　—　{obj['count']} 门 / {obj['credit']} 学分"
                if obj.get("required") is not None:
                    text += (f"　｜　要求 {float(obj['required']):g} 学分"
                             f" / 已修 {float(obj.get('earned', 0)):g} 学分")
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                item.setBackground(QColor("#eef2f7"))
                table.setItem(r, 0, item)
                table.setRowHeight(r, 32)
            else:
                is_selected = str(obj.get("code")) in selected_codes
                cells = [obj.get("code", ""), obj.get("name", ""),
                         f"{float(obj.get('credit', 0)):g}", obj.get("plan", ""),
                         "已选" if is_selected else ""]
                for col, val in enumerate(cells):
                    item = QTableWidgetItem(str(val))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if col in (2, 4):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if is_selected:
                        item.setBackground(QColor("#fff3b0"))
                    table.setItem(r, col, item)
                table.setRowHeight(r, 30)
                self._row_courses[r] = obj

        table.setColumnWidth(0, 110)
        table.setColumnWidth(1, 380)
        table.setColumnWidth(2, 70)
        table.setColumnWidth(3, 150)
        table.setColumnWidth(4, 70)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.itemDoubleClicked.connect(self._on_double_click)
        table.setToolTip("双击查看本学期开课情况")
        root.addWidget(table, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(34)
        close_btn.setMinimumWidth(110)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        root.addLayout(bar)

        self.resize(920, 740)

    def _on_double_click(self, item) -> None:
        course = self._row_courses.get(item.row())
        if not course:
            return
        if self._fetcher is None:
            QMessageBox.information(self, "提示", "尚未登录，请先点「开始运行」获取数据。")
            return
        if not self._term_id:
            QMessageBox.information(self, "提示", "缺少选课学期编号，请先点「开始运行」。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            classes = self._fetcher(str(course.get("code", "")), int(self._term_id))
        except Exception as exc:
            QMessageBox.critical(self, "获取失败", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        CourseClassesDialog(self, course, classes, self._semester_label).exec()


class CourseClassesDialog(QDialog):
    """某门课本学期的开课情况：所有教学班与上课时间；不开课时显示「无」。"""

    def __init__(self, parent=None, course: dict | None = None,
                 classes: list | None = None, semester: str = "") -> None:
        super().__init__(parent)
        course = course or {}
        classes = classes or []
        self.setWindowTitle("本学期开课情况")
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        title = QLabel(f"{course.get('name', '')}（{course.get('code', '')}）"
                       f"　｜　学分 {float(course.get('credit', 0)):g}")
        _big(title, 1.0)
        root.addWidget(title)
        root.addWidget(_hint(f"计划学期：{course.get('plan', '—')}"
                             + (f"　｜　{semester}" if semester else "")))

        if not classes:
            msg = QLabel("无 —— 本学期不开课")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _big(msg, 3.0)
            _set_color(msg, "#c42b1c")
            root.addWidget(msg, 1)
        else:
            columns = ["教学班代码", "序号", "校区", "任课教师",
                       "已录/名额", "上课周次", "上课时间", "上课地点"]
            table = QTableWidget(len(classes), len(columns))
            table.setHorizontalHeaderLabels(columns)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setShowGrid(False)
            table.setAlternatingRowColors(True)
            table.horizontalHeader().setHighlightSections(False)
            table.horizontalHeader().setStretchLastSection(False)

            for r, c in enumerate(classes):
                slots = c.get("slots") or []
                def join(key):
                    if not slots:
                        return "—"
                    return "\n".join(s.get(key, "") for s in slots)
                cells = [c.get("class_no", ""), c.get("seq", ""), c.get("campus", ""),
                         c.get("teacher", ""), f"{c.get('enrolled', '')}/{c.get('capacity', '')}",
                         join("weeks"), join("time"), join("room")]
                for col, val in enumerate(cells):
                    item = QTableWidgetItem(str(val))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if col in (1, 4):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(r, col, item)
                table.setRowHeight(r, max(30, 22 * max(1, len(slots))))

            for i, width in enumerate((95, 50, 90, 100, 85, 95, 130, 130)):
                table.setColumnWidth(i, width)
            table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
            root.addWidget(table, 1)
            root.addWidget(_hint(f"共 {len(classes)} 个教学班。"))

        bar = QHBoxLayout()
        bar.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(34)
        close_btn.setMinimumWidth(110)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        bar.addWidget(close_btn)
        root.addLayout(bar)

        self.resize(1000, 640)


# =============================================================================
# 工作线程：fetch（登录+抓取课程） / grab（抢课循环）
# =============================================================================
class Worker(threading.Thread):
    def __init__(self, phase: str, session: dict | None = None) -> None:
        super().__init__(daemon=True, name="dhu-" + phase)
        self.phase = phase
        self.session: dict = dict(session or {})
        self.stop_event = threading.Event()
        self.continue_event = threading.Event()

    def request_stop(self) -> None:
        self.stop_event.set()
        self.continue_event.set()

    def request_continue(self) -> None:
        self.continue_event.set()

    def _notify_user(self, message: str) -> None:
        """连续登录失败后阻塞并通知用户。

        TODO: 通知渠道尚未确定，当前只写入日志并把界面置为"已阻塞"。
              候选方案：Windows 原生 toast / QSystemTrayIcon 气泡 / 提示音 /
                       邮件或 Webhook / 置顶弹窗。
        """
        state.push_log("error", message)
        state.update(status="blocked", notify=message)

    def _login_with_retry(self, username: str, password: str, reason: str) -> bool:
        for attempt in range(1, MAX_RELOGIN_ATTEMPTS + 1):
            if self.stop_event.is_set():
                return False
            try:
                submit_h, query_h, public_h = login(username, password)
                self.session.update({"submit": submit_h, "query": query_h, "public": public_h})
                state.push_log("info", f"{reason}成功（第 {attempt} 次尝试）")
                return True
            except Exception as exc:
                state.push_log("warn", f"{reason}失败（{attempt}/{MAX_RELOGIN_ATTEMPTS}）：{exc}")
                if attempt < MAX_RELOGIN_ATTEMPTS and not self.stop_event.wait(2.0):
                    continue
                if self.stop_event.is_set():
                    return False
        self._notify_user(f"连续 {MAX_RELOGIN_ATTEMPTS} 次{reason}失败，已阻塞运行，请人工处理")
        return False

    def _ensure_session(self, username: str, password: str, reason: str) -> bool:
        if self.session.get("query"):
            state.push_log("info", "复用已有登录会话")
            return True
        return self._login_with_retry(username, password, reason)

    def _sleep(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self.stop_event.wait(0.1):
                return True
        return False

    def run(self) -> None:
        try:
            (username, password, term_id, active_mode, proxy_enabled,
             proxy_host, proxy_port, loop_interval, tasks) = load_config(CONFIG_PATH)
        except Exception as exc:
            state.push_log("error", f"读取 config.json 失败：{exc}")
            if self.phase == "fetch":
                state.update(selected={"status": "error", "error": f"读取配置失败：{exc}"},
                             pending={"status": "error", "error": f"读取配置失败：{exc}"})
            else:
                state.update(status="error")
            return

        api.init_proxy(proxy_enabled, proxy_host, proxy_port)

        if self.phase == "fetch":
            self._run_fetch(username, password, term_id)
        else:
            self._run_grab(username, password, term_id, active_mode, loop_interval, tasks)

    def _run_fetch(self, username: str, password: str, term_id: int) -> None:
        semester = TERM_BY_ID.get(term_id, "")
        state.update(selected={"status": "loading"}, pending={"status": "loading"})
        state.push_log("info", f"正在获取 {semester_label(semester)} 的已选课程与应读未读课程…")

        if not self._ensure_session(username, password, "登录"):
            state.update(selected={"status": "error", "error": "登录失败"},
                         pending={"status": "error", "error": "登录失败"})
            return

        # 1) 当前已选课程
        try:
            data = api.fetch_selected_courses(self.session["query"])
        except Exception as exc:
            state.push_log("error", f"获取已选课程失败：{exc}")
            state.update(selected={"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        else:
            payload = p.parse_selected_courses(data, semester)
            payload["status"] = "ok"
            payload["semester_label"] = semester_label(semester)
            payload["fetched_at"] = datetime.now().strftime("%H:%M:%S")
            state.update(selected=payload)
            conflicts = [c["name"] for c in payload["courses"] if c.get("conflict")]
            state.push_log("success",
                           f"当前已选课程：{len(payload['courses'])} 门，总学分 {payload['total_credit']}"
                           + ("；⚠ 存在时间冲突" if conflicts else ""))

        # 2) 应读未读课程（培养方案中尚未出分的课程）
        try:
            ts_data = api.fetch_ts_courses(username, semester, self.session["query"])
        except Exception as exc:
            state.push_log("error", f"获取应读未读课程失败：{exc}")
            state.update(pending={"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        else:
            pending = p.parse_pending_courses(ts_data)
            pending["status"] = "ok"
            pending["term_id"] = term_id
            pending["semester_label"] = semester_label(semester)
            state.update(pending=pending)
            state.push_log("success",
                           f"应读未读课程：{pending['count']} 门，合计 {pending['total_credit']} 学分")

    def _run_grab(self, username: str, password: str, term_id: int,
                  active_mode: str, loop_interval: float, tasks: list) -> None:
        state.update(active_mode=active_mode, status="running", success=False,
                     round=0, query_count=0, notify="")
        state.push_log("info", f"抢课启动：模式 {active_mode}，任务 {len(tasks)} 个，间隔 {loop_interval}s")

        if not self._ensure_session(username, password, "登录"):
            if not self.stop_event.is_set():
                state.update(status="error")
            return

        active_tasks = [t for t in tasks if t.mode == active_mode]
        if not active_tasks:
            state.push_log("warn", f"没有与激活模式 {active_mode} 匹配的任务，已停止")
            state.update(status="idle")
            return

        submit_h = self.session["submit"]
        query_h = self.session["query"]
        public_h = self.session["public"]

        try:
            while not self.stop_event.is_set():
                state.update(status="running")
                for task in active_tasks:
                    if self.stop_event.is_set():
                        break
                    run_task(task, submit_h, query_h, public_h, term_id)

                if self.stop_event.is_set():
                    break

                current = state.get_state()
                state.update(round=current["round"] + 1)
                if current["success"]:
                    break

                if active_mode == "Only_Submit":
                    self.continue_event.clear()
                    state.update(status="waiting")
                    state.push_log("info", "已完成一轮，等待点击「继续下一轮」")
                    self.continue_event.wait()
                    if self.stop_event.is_set():
                        break
                elif self._sleep(loop_interval):
                    break
        except RestartRequired:
            state.push_log("warn", "触发重新登录（进程内）")
            self.session.pop("query", None)
            if not self._login_with_retry(username, password, "重新登录"):
                if not self.stop_event.is_set():
                    state.update(status="error")
                return
        except Exception as exc:
            state.push_log("error", f"运行异常，已停止：{type(exc).__name__}: {exc}")
            state.update(status="error")
            return

        if state.get_state()["success"]:
            state.update(status="success")
        else:
            state.update(status="idle")
            if not self.stop_event.is_set():
                state.push_log("info", "已结束")


# =============================================================================
# 主窗口
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DHU 抢课助手")
        self.worker: Worker | None = None
        self.session: dict = {}

        self.config_page = ConfigPage()
        self.course_page = CoursePage()
        self.grab_page = GrabPage()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.config_page, "配置")
        self.tabs.addTab(self.course_page, "选课")
        self.tabs.addTab(self.grab_page, "抢课")

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(18, 10, 18, 12)
        bar_layout.setSpacing(10)
        self.dirty_label = _hint("")
        bar_layout.addWidget(self.dirty_label)
        bar_layout.addStretch(1)

        self.save_btn = QPushButton("保存配置")
        self.run_btn = QPushButton("开始运行")
        self.run_btn.setStyleSheet(PRIMARY_BUTTON_QSS)
        for btn, width in ((self.save_btn, 120), (self.run_btn, 160)):
            btn.setMinimumHeight(38)
            btn.setMinimumWidth(width)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bar_layout.addWidget(btn)
        self.save_btn.clicked.connect(self._save)
        self.run_btn.clicked.connect(self._start_run)
        root.addWidget(bar)
        self.bar = bar

        for page in (self.config_page, self.grab_page):
            page.dirty_changed.connect(self._on_dirty_changed)
        self.course_page.refresh_requested.connect(self._refresh_courses)
        self.course_page.timetable_requested.connect(self._show_timetable)
        self.course_page.pending_requested.connect(self._show_pending)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.grab_page.start_requested.connect(self._start_grab)
        self.grab_page.stop_requested.connect(self._stop)
        self.grab_page.continue_requested.connect(self._continue)

        self.statusBar().showMessage(f"配置文件：{CONFIG_PATH}")

        self._load_from_disk()

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.resize(1180, 800)
        self.setMinimumSize(1040, 720)
        self._on_tab_changed(0)
        self._tick()

    # ---------------- 配置读写 ----------------
    def _load_from_disk(self) -> None:
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        self.config_page.load(data)
        self.grab_page.load(data)
        self._on_dirty_changed(False)

    def _to_config_dict(self) -> dict:
        cfg = self.config_page.values()
        grab = self.grab_page.values()
        # 保持与历史 config.json 完全一致的键顺序
        return {
            "username": cfg["username"],
            "password": cfg["password"],
            "term_id": cfg["term_id"],
            "active_mode": grab["active_mode"],
            "loop_interval": grab["loop_interval"],
            "proxy": cfg["proxy"],
            "tasks": grab["tasks"],
        }

    def _save(self) -> bool:
        try:
            data = self._to_config_dict()
        except ValueError:
            QMessageBox.critical(self, "输入错误", "轮询间隔必须是数字，端口必须是整数。")
            return False
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self.config_page._clear_dirty()
        self.grab_page._clear_dirty()
        self._on_dirty_changed(False)
        self.statusBar().showMessage(f"已保存到 {CONFIG_PATH}", 4000)
        return True

    def _is_dirty(self) -> bool:
        return self.config_page.is_dirty() or self.grab_page.is_dirty()

    def _on_dirty_changed(self, _dirty: bool) -> None:
        dirty = self._is_dirty()
        self.dirty_label.setText("● 配置已修改，未保存" if dirty else "")
        _set_color(self.dirty_label, STATUS_COLORS["running"] if dirty else None)

    def _confirm_save_if_dirty(self) -> bool:
        if not self._is_dirty():
            return True
        answer = QMessageBox.question(
            self, "配置已修改",
            "配置有未保存的修改。是否先保存再继续？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save and not self._save():
            return False
        self._load_from_disk()
        return True

    # ---------------- 标签切换 ----------------
    def _on_tab_changed(self, _index: int) -> None:
        """「保存配置 / 开始运行」只在「配置」页显示。"""
        self.bar.setVisible(self.tabs.currentWidget() is self.config_page)

    def _show_timetable(self) -> None:
        selected = state.get_state().get("selected") or {}
        if not selected.get("courses"):
            QMessageBox.information(self, "提示", "还没有已选课程数据，请先点「开始运行」获取。")
            return
        TimetableDialog(self, selected).exec()

    def _show_pending(self) -> None:
        snap = state.get_state()
        pending = snap.get("pending") or {}
        if not pending.get("groups"):
            QMessageBox.information(self, "提示", "还没有应读未读课程数据，请先点「开始运行」获取。")
            return
        selected = snap.get("selected") or {}
        codes = {str(c.get("code")) for c in (selected.get("courses") or [])}
        PendingCoursesDialog(self, pending, codes, self._fetch_course_classes).exec()

    def _fetch_course_classes(self, course_code: str, term_id: int) -> list:
        """双击课程时调用：取该课程本学期的所有教学班与时间。"""
        headers = self.session.get("public") or self.session.get("query")
        if not headers:
            raise RuntimeError("尚未登录，请先点「开始运行」获取数据。")
        data = api.fetch_course_classes(course_code, term_id, headers)
        return p.parse_course_classes(data)

    # ---------------- 状态刷新 ----------------
    def _tick(self) -> None:
        running = self.worker is not None and self.worker.is_alive()
        if self.worker is not None and not running and self.worker.session.get("query"):
            self.session = dict(self.worker.session)

        snap = state.get_state()
        self.grab_page.refresh(snap)
        self.course_page.update_from_state(snap)

        self.run_btn.setEnabled(not running)
        self.save_btn.setEnabled(not running)
        self.grab_page.start_btn.setEnabled(not running)
        self.grab_page.stop_btn.setEnabled(running)
        self.grab_page.continue_btn.setEnabled(running and snap.get("status") == "waiting")

        if running:
            phase = "获取课程中" if (self.worker and self.worker.phase == "fetch") else "抢课运行中"
            self.statusBar().showMessage(
                f"{phase}…（{STATUS_LABELS.get(snap.get('status', ''), '')}）｜配置文件：{CONFIG_PATH}")
        elif snap.get("status") == "blocked":
            self.statusBar().showMessage(f"已阻塞：{snap.get('notify', '')}")
        else:
            self.statusBar().showMessage(f"配置文件：{CONFIG_PATH}")

    # ---------------- 动作 ----------------
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _start_run(self) -> None:
        if self._busy() or not self._confirm_save_if_dirty():
            return
        self.session = {}
        self.tabs.setCurrentWidget(self.course_page)
        self._launch("fetch")

    def _refresh_courses(self) -> None:
        if self._busy():
            return
        if self._is_dirty() and not self._confirm_save_if_dirty():
            return
        self._launch("fetch")

    def _start_grab(self) -> None:
        if self._busy() or not self._confirm_save_if_dirty():
            return
        self.grab_page.clear_logs()
        state.reset(active_mode=self.grab_page._current_mode())
        self.tabs.setCurrentWidget(self.grab_page)
        self._launch("grab")

    def _launch(self, phase: str) -> None:
        self.worker = Worker(phase, self.session)
        self.worker.start()
        self._tick()

    def _stop(self) -> None:
        if self._busy():
            state.push_log("warn", "收到停止请求，正在结束…")
            self.worker.request_stop()
        self._tick()

    def _continue(self) -> None:
        if self._busy():
            self.worker.request_continue()

    def closeEvent(self, event) -> None:
        if self._busy():
            answer = QMessageBox.question(
                self, "仍在运行",
                "任务仍在运行中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.request_stop()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("DHU 抢课助手")
    apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
