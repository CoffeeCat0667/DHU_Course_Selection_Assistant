import json
import re

from bs4 import BeautifulSoup
from colorama import Fore


def parse_public_query(raw: str, class_id: str) -> str | None:
    data = json.loads(raw)
    soup = BeautifulSoup(data['content'], 'html.parser')
    for tr in soup.find_all('tr'):
        if class_id in tr.get_text(strip=True):
            tds = [td.get_text(strip=True) for td in tr.find_all('td') if td.get_text(strip=True)]
            total, remain = tds[5], tds[7]
            time_table = tr.find('table')
            schedule = []
            if time_table:
                for time_tr in time_table.find_all('tr'):
                    cols = time_tr.find_all('td')
                    schedule.append(f"{cols[0].get_text(strip=True)} {cols[1].get_text(strip=True)} {cols[2].get_text(strip=True)}")
            print(Fore.GREEN + f"=== 教学班{class_id}信息 ===")
            print(f"课程编码：{tds[0]}  课程名称：{tds[1]}  教学班代码：{tds[3]}")
            print(f"总名额：{total}  录取人数：{remain}  剩余人数：{int(total) - int(remain)}")
            print(f"授课教师：{tds[9]}")
            for s in schedule:
                print(f"  - {s}")
            return str(int(total) - int(remain))
    print(Fore.RED + f"未找到代码{class_id}的相关信息,正在重试...")
    return None


def parse_recommended(ts_data: dict, honor_data: dict, semester: str) -> dict:
    """从 initTSCourses / initHonorCourses 的返回中提取本学期推荐选读课程。

    判定规则（对真实接口实测得出）：
        tsCourses.crScores[课程编号] 中存在一条 [学期, 成绩, 学分, ...]，
        且 学期 == semester 且 成绩 is None
        —— 即"按培养方案应在本学期修读、但尚未出分"的课程。

    返回：{semester, courses:[{code,name,credit,category}], total_credit,
           honor:[{group,code,name,credit}], honor_total}
    """
    ts = (ts_data or {}).get("tsCourses") or {}

    # 课程编号 -> (课程名称, 学分, 课程类别)
    info: dict = {}
    for key in ("tsCourseMapNoCagegory", "tsCourseMapWidthCategory", "categorySCGMap"):
        for category, items in (ts.get(key) or {}).items():
            if not isinstance(items, list):
                continue
            for c in items:
                if isinstance(c, dict) and c.get("courseCode"):
                    info.setdefault(c["courseCode"],
                                    (c.get("courseName", ""), c.get("credit", 0.0), category))

    courses: list = []
    total = 0.0
    for code, records in (ts.get("crScores") or {}).items():
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, list) or len(rec) < 3:
                continue
            term, score, credit = rec[0], rec[1], rec[2]
            if term != semester or score is not None:
                continue
            name, _ref_credit, category = info.get(code, ("", credit, ""))
            try:
                credit_val = float(credit)
            except (TypeError, ValueError):
                credit_val = 0.0
            courses.append({
                "code": str(code),
                "name": name or "(未在选课对照表中找到)",
                "credit": credit_val,
                "category": category,
            })
            total += credit_val
            break
    courses.sort(key=lambda x: (x["category"], x["code"]))

    honor: list = []
    honor_total = 0.0
    for group, items in ((honor_data or {}).get("hornorCrs") or {}).items():
        for c in (items or []):
            try:
                xf = float(c.get("XF") or 0)
            except (TypeError, ValueError):
                xf = 0.0
            honor.append({"group": group, "code": c.get("KCBH", ""),
                          "name": c.get("KCMC", ""), "credit": xf})
            honor_total += xf

    return {
        "semester": semester,
        "courses": courses,
        "total_credit": round(total, 2),
        "honor": honor,
        "honor_total": round(honor_total, 2),
    }


# ---------------------------------------------------------------------------
# 当前已选课程 / 课程表
# ---------------------------------------------------------------------------
WEEKDAY_INDEX = {"周一": 0, "周二": 1, "周三": 2, "周四": 3,
                 "周五": 4, "周六": 5, "周日": 6, "周天": 6}
PERIOD_COUNT = 13


def parse_class_time(text: str) -> list:
    """'周三.7.8.9节' -> [(2, 7), (2, 8), (2, 9)]

    星期索引用 0=周一 … 6=周日；节次用 1..13。
    """
    result: list = []
    if not text:
        return result
    rest = str(text).strip()
    day = None
    for name, idx in WEEKDAY_INDEX.items():
        if rest.startswith(name):
            day = idx
            rest = rest[len(name):].lstrip(".。")
            break
    if day is None:
        return result
    for token in re.split(r"[.,、 ]+", rest):
        digits = re.sub(r"[^0-9]", "", token)
        if digits:
            period = int(digits)
            if 1 <= period <= PERIOD_COUNT:
                result.append((day, period))
    return result


def format_weeks(text: str) -> str:
    """'1-16周' -> '第1-16周'"""
    value = (text or "").strip()
    if value and value.endswith("周") and not value.startswith("第"):
        return "第" + value
    return value


def parse_selected_courses(data: dict, semester: str = "") -> dict:
    """把 initSelCourses 的返回整理成界面用的结构。

    返回：{semester, courses:[{code,name,credit,category,class_no,teacher,
           conflict,slots:[{weeks,time,room,periods}]}], total_credit,
           report_credit, pending_credit}
    """
    courses: list = []
    total = 0.0
    for c in (data or {}).get("enrollCourses") or []:
        try:
            credit = float(c.get("credit") or 0)
        except (TypeError, ValueError):
            credit = 0.0
        slots: list = []
        for n in (1, 2, 3, 4):
            weeks = c.get("useWeek" + str(n)) or ""
            time_text = c.get("classTime" + str(n)) or ""
            room = c.get("classRoom" + str(n)) or ""
            if not (weeks or time_text or room):
                continue
            slots.append({
                "weeks": format_weeks(weeks),
                "time": str(time_text),
                "room": str(room),
                "periods": parse_class_time(time_text),
            })
        courses.append({
            "code": str(c.get("courseCode", "")),
            "name": str(c.get("courseName", "")),
            "credit": credit,
            "category": c.get("catetory") or "",
            "class_no": c.get("classNo", ""),
            "teacher": c.get("teachName", ""),
            "conflict": bool(c.get("conflict")),
            "slots": slots,
        })
        total += credit

    credits = (data or {}).get("credits") or []
    report = credits[0] if len(credits) > 0 else round(total, 2)
    pending = credits[1] if len(credits) > 1 else 0.0
    return {
        "semester": semester,
        "courses": courses,
        "total_credit": round(total, 2),
        "report_credit": report,
        "pending_credit": pending,
    }


PLAN_LABELS = {
    "1A": "大一上", "1B": "大一下", "2A": "大二上", "2B": "大二下",
    "3A": "大三上", "3B": "大三下", "4A": "大四上", "4B": "大四下",
}


def format_plan(text: str) -> str:
    """'3A' -> '大三上'；'20262027a' -> '2026-2027学年 第 1 学期'"""
    value = (text or "").strip()
    if not value:
        return "—"
    if value in PLAN_LABELS:
        return PLAN_LABELS[value]
    if len(value) >= 9 and value[:8].isdigit():
        return f"{value[:4]}-{value[4:8]}学年 第 {1 if value[8] == 'a' else 2} 学期"
    return value


def _to_credit(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _required_credits(required_map: dict, category: str):
    """取某类别的要求学分；先精确匹配，再尝试 'xxx-类别' 后缀匹配。"""
    if category in required_map:
        return _to_credit(required_map[category])
    for key, value in (required_map or {}).items():
        if key == category or str(key).endswith("-" + str(category)):
            return _to_credit(value)
    return None


def parse_course_classes(data) -> list:
    """解析 getCourseTimeTableInfo 的返回，列出该课程本学期所有教学班。

    返回 [{code, name, college, class_no, seq, capacity, applied, enrolled,
           campus, teacher, slots:[{weeks, time, room}]}]
    空列表表示本学期不开课。
    """
    if isinstance(data, dict):
        content = data.get("content") or ""
    else:
        try:
            content = (json.loads(data) or {}).get("content") or ""
        except Exception:
            content = str(data or "")
    if not content:
        return []

    soup = BeautifulSoup(content, "html.parser")
    classes: list = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        slots: list = []
        inner = tr.find("table")
        if inner:
            for row in inner.find_all("tr"):
                cols = [c.get_text(strip=True) for c in row.find_all("td")]
                if len(cols) >= 3:
                    slots.append({"weeks": cols[0], "time": cols[1], "room": cols[2]})
        classes.append({
            "code": texts[0] if len(texts) > 0 else "",
            "name": texts[1] if len(texts) > 1 else "",
            "college": texts[2] if len(texts) > 2 else "",
            "class_no": texts[3] if len(texts) > 3 else "",
            "seq": texts[4] if len(texts) > 4 else "",
            "capacity": texts[5] if len(texts) > 5 else "",
            "applied": texts[6] if len(texts) > 6 else "",
            "enrolled": texts[7] if len(texts) > 7 else "",
            "campus": texts[8] if len(texts) > 8 else "",
            "teacher": texts[9] if len(texts) > 9 else "",
            "slots": slots,
        })
    return classes


def parse_pending_courses(ts_data: dict) -> dict:
    """培养方案中「应读未读」的课程，按课程类别分组。

    判定：tsCourses.crScores[课程编号] 中不存在任何非空成绩（即从未出分）。
    返回：{groups:[{category, courses:[{code,name,credit,plan}], credit, count}],
           count, total_credit}
    """
    ts = (ts_data or {}).get("tsCourses") or {}

    catalogue: dict = {}
    for key in ("tsCourseMapNoCagegory", "tsCourseMapWidthCategory", "categorySCGMap"):
        for category, items in (ts.get(key) or {}).items():
            if not isinstance(items, list):
                continue
            for c in items:
                if not isinstance(c, dict) or not c.get("courseCode"):
                    continue
                code = str(c["courseCode"])
                catalogue.setdefault(code, {
                    "code": code,
                    "name": str(c.get("courseName", "")),
                    "credit": _to_credit(c.get("credit")),
                    "plan": format_plan(c.get("yearTerm", "")),
                    "category": category,
                })

    scores = ts.get("crScores") or {}
    required_map = ts.get("tsCredits") or {}
    grouped: dict = {}
    earned: dict = {}
    total = 0.0
    for course in catalogue.values():
        records = scores.get(course["code"]) or []
        has_score = any(isinstance(r, list) and len(r) > 1 and r[1] is not None
                        for r in records)
        if has_score:
            earned[course["category"]] = earned.get(course["category"], 0.0) + course["credit"]
            continue
        grouped.setdefault(course["category"], []).append(course)
        total += course["credit"]

    groups: list = []
    order = ts.get("bigSortKinds") or []
    for category in list(order) + sorted(k for k in grouped if k not in order):
        items = grouped.pop(category, None)
        if not items:
            continue
        items.sort(key=lambda x: (x["plan"], x["code"]))
        groups.append({
            "category": category,
            "courses": items,
            "count": len(items),
            "credit": round(sum(x["credit"] for x in items), 2),
            "required": _required_credits(required_map, category),
            "earned": round(earned.get(category, 0.0), 2),
            "is_elective": "选修" in str(category),
        })

    return {
        "groups": groups,
        "count": sum(g["count"] for g in groups),
        "total_credit": round(total, 2),
    }
