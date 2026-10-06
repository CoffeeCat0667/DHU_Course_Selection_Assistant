import threading
from colorama import Fore
import api
import parser as p
import state


class RestartRequired(Exception):
    pass


def _log(level, msg):
    colors = {"success": Fore.GREEN, "warn": Fore.YELLOW, "error": Fore.RED, "info": Fore.WHITE}
    print(colors.get(level, Fore.WHITE) + msg)
    state.push_log(level, msg)


def _query_seats(task, query_h: dict, public_h: dict) -> list[dict]:
    query_data = (
        "sEcho=1&iColumns=10&sColumns=&iDisplayStart=0&iDisplayLength=-1"
        "&mDataProp_0=cttId&mDataProp_1=classNo&mDataProp_2=maxCnt&mDataProp_3=applyCnt"
        "&mDataProp_4=enrollCnt&mDataProp_5=priorMajors&mDataProp_6=techName"
        "&mDataProp_7=cttId&mDataProp_8=cttId&mDataProp_9=cttId"
        "&iSortCol_0=0&sSortDir_0=asc&iSortingCols=1"
        "&bSortable_0=false&bSortable_1=false&bSortable_2=false&bSortable_3=false"
        "&bSortable_4=false&bSortable_5=false&bSortable_6=false&bSortable_7=false"
        f"&bSortable_8=false&bSortable_9=false&courseCode={task.main_id}"
    )
    try:
        result = api.query(query_data, query_h)
        state.update(query_count=state.get_state()["query_count"] + 1)
        return result
    except Exception:
        return []


def _public_query_seats(task, class_id: str, public_h: dict, term_id: int) -> list[dict]:
    data = f"kcbh={task.main_id}&termId={term_id}"
    raw = api.public_query(data, public_h)
    state.update(query_count=state.get_state()["query_count"] + 1)
    result = p.parse_public_query(raw, class_id)
    if result is None:
        _log("error", f"{class_id} 未找到课程信息，正在重启程序...")
        raise RestartRequired()
    _log("info", f"{class_id} 查询余量: {result}")
    return [{"cttId": class_id, "excessCnt": int(result)}]


def _only_submit_thread(ctt_id: str, submit_h: dict):
    result = api.submit(f"cttId={ctt_id}&needMaterial=false", submit_h)
    if result.get("success"):
        _log("success", f"{ctt_id} 选课成功")
        state.update(success=True, status="success")
    else:
        _log("info", f"{ctt_id} 提交返回: {result.get('msg', result)}")


def run_task(task, submit_h: dict, query_h: dict, public_h: dict, term_id: int = 85) -> int:
    if task.mode == "Only_Submit":
        threads = [threading.Thread(target=_only_submit_thread, args=(task.target_ids[0], submit_h))
                   for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        return 1 if state.get_state()["success"] else 0

    seats = _query_seats(task, query_h, public_h)

    for cid in task.target_ids:
        data_list = seats if seats else _public_query_seats(task, cid, public_h, term_id)
        for item in data_list:
            if item["cttId"] != cid:
                continue
            if item["excessCnt"] <= 0:
                _log("warn", f"{cid} 名额不足：{item['excessCnt']}")
                return 0

            if task.mode == "FQTS":
                try:
                    resp = api.submit(f"cttId={cid}&needMaterial=false", submit_h)
                    if resp.get("success"):
                        _log("success", f"{cid} 选课成功")
                        state.update(success=True, status="success")
                        return 1
                    _log("info", f"{cid} 选课失败: {resp}")
                except Exception:
                    _log("error", "程序运行异常，正在重启程序...")
                    raise RestartRequired()

            elif task.mode == "FQTDLS":
                del_data = f"courseCode={task.main_id}&classNo={task.del_class_no}&cancelType=1"
                try:
                    del_resp = api.delete(del_data, submit_h)
                    if not del_resp.get("success"):
                        _log("error", f"删除原始课程失败！{del_resp}")
                        return -1
                except Exception:
                    _log("error", "程序运行异常,无法删除原始课程，正在重启程序...")
                    raise RestartRequired()
                try:
                    resp = api.submit(f"cttId={cid}&needMaterial=false", submit_h)
                except Exception:
                    _log("error", "程序运行异常,无法选入新增课程，正在重启程序...")
                    raise RestartRequired()
                if resp.get("success"):
                    _log("success", f"{cid} 选课成功")
                    state.update(success=True, status="success")
                    return 1
                rollback = api.submit(f"cttId={task.del_raw_id}&needMaterial=false", submit_h)
                _log("info", f"{cid} 选课失败: {resp}")
                if not rollback.get("success"):
                    _log("error", f"无法回滚到原始课程！{rollback}")
                    return -3
    return 0
