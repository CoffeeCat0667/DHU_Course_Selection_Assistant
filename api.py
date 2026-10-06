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
