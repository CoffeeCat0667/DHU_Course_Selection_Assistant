import ssl
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime

PROXIES = None


def init_proxy(enabled: bool, host: str, port: int):
    global PROXIES
    if enabled:
        PROXIES = {'http': f'http://{host}:{port}', 'https': f'http://{host}:{port}'}
    else:
        PROXIES = None


def _log(url: str, raw: str):
    with open('log.txt', 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {url}\n{raw}\n\n")


def _make_ssl_session() -> requests.Session:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= 0x4

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)

    s = requests.Session()
    s.mount('https://', _Adapter())
    return s


def query(data: str, headers: dict) -> list[dict]:
    url = 'https://jwgl.dhu.edu.cn/dhu/selectcourse/initACC'
    resp = _make_ssl_session().post(url, headers=headers, data=data, proxies=PROXIES, verify=False)
    _log(url, resp.text)
    return [{"cttId": str(item["cttId"]), "excessCnt": item["maxCnt"] - item["enrollCnt"]}
            for item in resp.json()["aaData"]]


def public_query(data: str, headers: dict) -> str:
    url = 'https://jwgl.dhu.edu.cn/dhu/PublicQuery/getCourseTimeTableInfo'
    resp = _make_ssl_session().post(url, headers=headers, data=data, proxies=PROXIES, verify=False)
    _log(url, resp.text)
    return resp.text


def submit(data: str, headers: dict) -> dict:
    return _post('https://jwgl.dhu.edu.cn/dhu/selectcourse/scSubmit', headers, data)


def delete(data: str, headers: dict) -> dict:
    return _post('https://jwgl.dhu.edu.cn/dhu/selectcourse/cancelSC', headers, data)


def _post(url: str, headers: dict, data: str) -> dict:
    resp = requests.post(url, headers=headers, data=data, proxies=PROXIES, verify=False)
    _log(url, resp.text)
    return resp.json()


def _post_form(url: str, headers: dict, data: dict) -> dict:
    """POST 表单（字典）。必须丢弃硬编码的 Content-Length，交给 requests 重算。"""
    h = {k: v for k, v in headers.items() if k.lower() != "content-length"}
    resp = requests.post(url, headers=h, data=data, proxies=PROXIES, verify=False)
    _log(url, resp.text)
    return resp.json()


def fetch_ts_courses(stud_no: str, semester: str, headers: dict) -> dict:
    """本学期选课对照表（推荐选读课程与学分的数据源）。"""
    return _post_form(
        'https://jwgl.dhu.edu.cn/dhu/selectcourse/initTSCourses',
        headers,
        {'studNo': stud_no, 'scSemester': semester, 'type': 'selectCourse'},
    )


def fetch_honor_courses(stud_no: str, semester: str, headers: dict) -> dict:
    """荣誉课程列表。"""
    return _post_form(
        'https://jwgl.dhu.edu.cn/dhu/selectcourse/initHonorCourses',
        headers,
        {'studNo': stud_no, 'scSemester': semester},
    )


def fetch_course_classes(course_code: str, term_id: int, headers: dict) -> dict:
    """某门课本学期的开课情况（所有教学班与上课时间）。

    返回 {"content": "<table>...</table>", "success": true}；
    课程本学期不开课时 content 为空字符串。
    """
    return _post_form(
        'https://jwgl.dhu.edu.cn/dhu/PublicQuery/getCourseTimeTableInfo',
        headers,
        {'kcbh': course_code, 'termId': term_id},
    )


def fetch_selected_courses(headers: dict) -> dict:
    """当前已选课程（「查看自己选课情况」页的数据源）。

    返回 result.enrollCourses，每门含 courseCode / courseName / credit /
    catetory / classNo / teachName / classTime1~4 / classRoom1~4 /
    useWeek1~4 / conflict，以及 result.credits = [已选学分, 待筛选学分]。
    """
    return _post_form(
        'https://jwgl.dhu.edu.cn/dhu/selectcourse/initSelCourses',
        headers,
        {},
    )
