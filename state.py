"""运行状态：线程安全的共享快照，供 Qt 界面轮询读取。

Ver3.0：移除 Flask 时代的 SSE 队列与 event_stream()，
        改为纯状态容器 + Qt 侧 QTimer 轮询，并给日志加上自增 id
        以便界面做增量渲染（原实现按索引追踪，日志裁剪后会错乱）。
"""

import threading
from datetime import datetime

MAX_LOGS = 200

_lock = threading.Lock()
_log_seq = 0
_state = {
    "active_mode": "",
    "status": "idle",        # idle | running | waiting | success | error | blocked
    "success": False,
    "round": 0,
    "query_count": 0,
    "notify": "",            # 阻塞时给用户的通知文本
    "selected": None,        # 选课页数据：{status, semester, courses, total_credit, ...}
    "pending": None,         # 应读未读课程：{groups, count, total_credit}
    "logs": [],              # [{id, time, level, msg}]
}


def reset(**kwargs):
    """开始新一轮运行前清空状态与日志。"""
    global _log_seq
    with _lock:
        _state.update({
            "active_mode": "",
            "status": "idle",
            "success": False,
            "round": 0,
            "query_count": 0,
            "notify": "",
            "selected": None,
            "pending": None,
            "logs": [],
        })
        _state.update(kwargs)
        _log_seq = 0


def update(**kwargs):
    with _lock:
        _state.update(kwargs)


def push_log(level: str, msg: str):
    global _log_seq
    with _lock:
        _log_seq += 1
        _state["logs"].append({
            "id": _log_seq,
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        })
        if len(_state["logs"]) > MAX_LOGS:
            _state["logs"].pop(0)


def get_state():
    with _lock:
        return {**_state, "logs": list(_state["logs"])}
