"""DHU 抢课助手 —— 单一入口 Qt 应用

Ver3.0 前端重构：
  * 彻底移除 Flask / SSE / Web 监控面板，监控界面由 Qt 原生实现；
  * 原 config_editor.py 的配置界面并入本文件，不再单独成文件；
  * 单窗口 + 两个标签页：配置 / 监控；
  * 控制台模式取消；
  * 出错后的重新登录改为进程内进行，连续失败 MAX_RELOGIN_ATTEMPTS 次后阻塞并通知用户。

运行：python main.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

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
import state
from auth import login
from loader import load_config
from strategies import RestartRequired, run_task

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 重新登录：连续失败达到该次数则阻塞运行并通知用户
MAX_RELOGIN_ATTEMPTS = 5

# 学期显示名 → term_id 映射，20262027a=86 起，每学期+1，a=秋，s=春
TERMS: dict[str, int] = {}
_tid = 86
for _y in range(2026, 2034):
    TERMS[f"{_y}{_y + 1}a"] = _tid
    _tid += 1
    TERMS[f"{_y}{_y + 1}s"] = _tid
    _tid += 1
TERM_LABELS = list(TERMS.keys())
TERM_BY_ID = {v: k for k, v in TERMS.items()}

# (值, 标题, 说明)
MODES = [
    ("Only_Submit", "直接抢课 (Only_Submit)", "不查名额，直接并发提交"),
    ("FQTS", "查询后抢课 (FQTS)", "先查名额，有余量再提交"),
    ("FQTDLS", "调课模式 (FQTDLS)", "退旧课后选新课，失败自动回滚"),
]
MODE_VALUES = [m[0] for m in MODES]
# 需要显示"查询次数"的模式（原 Web 面板因键名不匹配导致该卡片永不显示，这里修正）
QUERY_MODES = {"FQTS", "FQTDLS"}
MODE_LABELS = {value: label for value, label, _desc in MODES}

TABLE_COLUMNS = [
    ("mode", "模式", 130),
    ("main_id", "课程代码", 100),
    ("target_ids", "目标教学班ID", 220),
    ("del_class_no", "退课班号", 100),
    ("del_raw_id", "回滚ID", 100),
]

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

# 仅作用于个别按钮，不设全局 QSS，避免破坏 windows11 原生渲染
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
    """次要说明文字：主题自适应的灰 + 小一号字。"""
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


# =============================================================================
# 配置页（原 config_editor.py 的内容）
# =============================================================================
class ConfigPage(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.tasks: list[dict] = []
        self._dirty = False
        self._loading = False
        self._build()
        self.load_from_disk()

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self._build_credentials())
        left.addWidget(self._build_loop())
        left.addWidget(self._build_proxy())
        left.addWidget(self._build_modes())
        left.addStretch(1)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(420)
        body.addWidget(left_wrap)

        body.addWidget(self._build_task_list(), 1)
        root.addLayout(body, 1)

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

    def _build_loop(self) -> QGroupBox:
        box = QGroupBox("循环设置")
        form = QFormLayout(box)
        form.setContentsMargins(14, 16, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.interval_edit = QLineEdit("3")
        self.interval_edit.setMinimumHeight(32)
        self.interval_edit.setMaximumWidth(96)
        self.interval_edit.textChanged.connect(self._mark_dirty)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.interval_edit)
        row.addWidget(_hint("秒（FQTS / FQTDLS 生效）", wrap=False))
        row.addStretch(1)
        form.addRow("轮询间隔", row)
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

        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in TABLE_COLUMNS])
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
        for i, (_key, _title, width) in enumerate(TABLE_COLUMNS):
            self.table.setColumnWidth(i, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._edit_task)
        v.addWidget(self.table)
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

    # ---------------- 交互 ----------------
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

    def _update_term_hint(self) -> None:
        self.term_id_label.setText(f"term_id={TERMS.get(self.term_combo.currentText(), 86)}")

    def _sync_proxy_enabled(self, checked: bool) -> None:
        self.proxy_host.setEnabled(checked)
        self.proxy_port.setEnabled(checked)

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

    # ---------------- 读写 config.json ----------------
    def to_config_dict(self) -> dict:
        return {
            "username": self.username_edit.text().strip(),
            "password": self.password_edit.text(),
            "term_id": TERMS.get(self.term_combo.currentText(), 86),
            "active_mode": self._current_mode(),
            "loop_interval": float(self.interval_edit.text().strip() or 3),
            "proxy": {
                "enabled": self.proxy_enabled.isChecked(),
                "host": self.proxy_host.text().strip(),
                "port": int(self.proxy_port.text().strip() or 8888),
            },
            "tasks": self.tasks,
        }

    def save_to_disk(self) -> bool:
        try:
            data = self.to_config_dict()
        except ValueError:
            QMessageBox.critical(self, "输入错误", "轮询间隔必须是数字，端口必须是整数。")
            return False
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self._clear_dirty()
        return True

    def load_from_disk(self) -> None:
        self._loading = True
        try:
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
                self.username_edit.setText(data.get("username", ""))
                self.password_edit.setText(data.get("password", ""))
                self.term_combo.setCurrentText(TERM_BY_ID.get(data.get("term_id", 86), TERM_LABELS[0]))
                self._set_mode(data.get("active_mode", "Only_Submit"))
                self.interval_edit.setText(str(data.get("loop_interval", 3)))
                proxy = data.get("proxy") or {}
                self.proxy_enabled.setChecked(proxy.get("enabled", True))
                self.proxy_host.setText(proxy.get("host", "localhost"))
                self.proxy_port.setText(str(proxy.get("port", 8888)))
                self.tasks = data.get("tasks") or []
        finally:
            self._loading = False
        self._update_term_hint()
        self._sync_proxy_enabled(self.proxy_enabled.isChecked())
        self._on_mode_changed()
        self._refresh_table()
        self._clear_dirty()


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
# 监控页（替代原 web_ui.html）
# =============================================================================
class MonitorPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._last_log_id = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

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
        root.addLayout(cards)

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
        root.addWidget(log_box, 1)

        self.refresh(state.get_state())

    def _make_card(self, title: str) -> tuple[QGroupBox, QLabel]:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 16, 12, 12)
        value = QLabel("—")
        font = QFont(value.font())
        size = font.pointSizeF()
        if size > 0:
            font.setPointSizeF(size + 2.0)
        font.setBold(True)
        value.setFont(font)
        v.addWidget(value)
        return box, value

    def clear(self) -> None:
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
# 抢课工作线程
# =============================================================================
class Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="dhu-runner")
        self.stop_event = threading.Event()
        self.continue_event = threading.Event()
        self.submit_h: dict | None = None
        self.query_h: dict | None = None
        self.public_h: dict | None = None

    # ---------------- 外部控制 ----------------
    def request_stop(self) -> None:
        self.stop_event.set()
        self.continue_event.set()

    def request_continue(self) -> None:
        self.continue_event.set()

    # ---------------- 通知（方式待定）----------------
    def _notify_user(self, message: str) -> None:
        """连续登录失败后阻塞并通知用户。

        TODO: 通知渠道尚未确定，当前只写入日志并把界面置为"已阻塞"。
              候选方案（任选其一后在此实现）：
                * Windows 原生 toast 通知（winrt / win10toast）
                * 系统托盘气泡（QSystemTrayIcon.showMessage）
                * 播放提示音（QApplication.beep / winsound）
                * 邮件或企业微信 / Server 酱等 Webhook
                * 独立置顶弹窗（QMessageBox），需人工确认后解除阻塞
        """
        state.push_log("error", message)
        state.update(status="blocked", notify=message)

    # ---------------- 登录 ----------------
    def _login_with_retry(self, username: str, password: str, reason: str) -> bool:
        for attempt in range(1, MAX_RELOGIN_ATTEMPTS + 1):
            if self.stop_event.is_set():
                return False
            try:
                self.submit_h, self.query_h, self.public_h = login(username, password)
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

    # ---------------- 主流程 ----------------
    def _sleep(self, seconds: float) -> bool:
        """可被打断的等待；返回 True 表示收到停止请求。"""
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
            state.update(status="error")
            return

        api.init_proxy(proxy_enabled, proxy_host, proxy_port)
        state.update(active_mode=active_mode, status="running", success=False,
                     round=0, query_count=0, notify="")
        state.push_log("info", f"启动：模式 {active_mode}，任务 {len(tasks)} 个，间隔 {loop_interval}s")

        if not self._login_with_retry(username, password, "登录"):
            if not self.stop_event.is_set():
                state.update(status="error")
            return

        active_tasks = [t for t in tasks if t.mode == active_mode]
        if not active_tasks:
            state.push_log("warn", f"没有与激活模式 {active_mode} 匹配的任务，已停止")
            state.update(status="idle")
            return

        try:
            while not self.stop_event.is_set():
                state.update(status="running")
                for task in active_tasks:
                    if self.stop_event.is_set():
                        break
                    run_task(task, self.submit_h, self.query_h, self.public_h, term_id)

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

        self.config_page = ConfigPage()
        self.monitor_page = MonitorPage()

        tabs = QTabWidget()
        tabs.addTab(self.config_page, "配置")
        tabs.addTab(self.monitor_page, "监控")
        self.tabs = tabs

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(tabs, 1)
        self.setCentralWidget(central)

        # 底部工具栏
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(18, 10, 18, 12)
        bar_layout.setSpacing(10)

        self.dirty_label = _hint("")
        bar_layout.addWidget(self.dirty_label)
        bar_layout.addStretch(1)

        self.continue_btn = QPushButton("继续下一轮")
        self.continue_btn.setMinimumHeight(38)
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.clicked.connect(self._continue)

        self.start_btn = QPushButton("开始抢课")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setMinimumWidth(150)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet(PRIMARY_BUTTON_QSS)
        self.start_btn.clicked.connect(self._start)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self._stop)

        self.save_btn = QPushButton("保存配置")
        self.save_btn.setMinimumHeight(38)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save)

        for btn in (self.save_btn, self.continue_btn, self.start_btn, self.stop_btn):
            bar_layout.addWidget(btn)

        root.addWidget(bar)

        self.config_page.dirty_changed.connect(self._on_dirty_changed)
        self._on_dirty_changed(self.config_page.is_dirty())

        self.statusBar().showMessage(f"配置文件：{CONFIG_PATH}")

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.resize(1180, 780)
        self.setMinimumSize(1000, 700)
        self._tick()

    # ---------------- 状态刷新 ----------------
    def _tick(self) -> None:
        running = self.worker is not None and self.worker.is_alive()
        snap = state.get_state()
        self.monitor_page.refresh(snap)

        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.save_btn.setEnabled(not running)
        self.continue_btn.setEnabled(running and snap.get("status") == "waiting")

        if running:
            self.statusBar().showMessage(
                f"运行中…（{STATUS_LABELS.get(snap.get('status', ''), '')}）｜配置文件：{CONFIG_PATH}")
        elif snap.get("status") == "blocked":
            self.statusBar().showMessage(f"已阻塞：{snap.get('notify', '')}")
        else:
            self.statusBar().showMessage(f"配置文件：{CONFIG_PATH}")

    def _on_dirty_changed(self, dirty: bool) -> None:
        self.dirty_label.setText("● 配置已修改，未保存" if dirty else "")
        _set_color(self.dirty_label, STATUS_COLORS["running"] if dirty else None)

    # ---------------- 按钮动作 ----------------
    def _save(self) -> None:
        if self.config_page.save_to_disk():
            self.statusBar().showMessage(f"已保存到 {CONFIG_PATH}", 4000)

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        if self.config_page.is_dirty():
            answer = QMessageBox.question(
                self, "配置已修改",
                "配置有未保存的修改。是否先保存再开始？\n\n保存：写入 config.json 后开始\n"
                "放弃：忽略修改，按磁盘上现有配置开始",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self.config_page.save_to_disk():
                return

        self.config_page.load_from_disk()
        self.monitor_page.clear()
        state.reset(active_mode=self.config_page._current_mode())
        self.tabs.setCurrentWidget(self.monitor_page)

        self.worker = Worker()
        self.worker.start()
        self._tick()

    def _stop(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            state.push_log("warn", "收到停止请求，正在结束…")
            self.worker.request_stop()
        self._tick()

    def _continue(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.request_continue()

    # ---------------- 关闭 ----------------
    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.is_alive():
            answer = QMessageBox.question(
                self, "仍在运行",
                "抢课仍在运行中，确定要退出吗？\n退出会立即停止抢课。",
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
