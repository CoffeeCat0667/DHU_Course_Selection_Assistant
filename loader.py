import json
from dataclasses import dataclass


@dataclass
class Task:
    main_id: str
    target_ids: list
    mode: str           # "Only_Submit" | "FQTS" | "FQTDLS"
    del_class_no: str = ""
    del_raw_id: str = ""


def load_config(path: str = "config.json") -> tuple:
    """Returns (username, password, term_id, active_mode, proxy_enabled, proxy_host, proxy_port, loop_interval, tasks)"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    username = data.get("username", "")
    password = data.get("password", "")
    term_id = data.get("term_id", 85)
    active_mode = data.get("active_mode", "Only_Submit")
    proxy = data.get("proxy", {})
    proxy_enabled = proxy.get("enabled", True)
    proxy_host = proxy.get("host", "localhost")
    proxy_port = proxy.get("port", 8888)
    loop_interval = float(data.get("loop_interval", 3))
    tasks = [
        Task(
            main_id=t.get("main_id", ""),
            target_ids=t.get("target_ids", []),
            mode=t.get("mode", "Only_Submit"),
            del_class_no=t.get("del_class_no", ""),
            del_raw_id=t.get("del_raw_id", ""),
        )
        for t in data.get("tasks", [])
    ]
    return username, password, term_id, active_mode, proxy_enabled, proxy_host, proxy_port, loop_interval, tasks
