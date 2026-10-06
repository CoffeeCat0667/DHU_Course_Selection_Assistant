from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login(username: str, password: str) -> tuple[dict, dict, dict]:
    opt = Options()
    for arg in ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
                '--start-maximized', '--blink-settings=imagesEnabled=false',
                '--disable-plugins', '--disable-extensions']:
        opt.add_argument(arg)

    svc = EdgeService()
    svc.service_args = ['--connect-timeout=3000', '--read-timeout=3000']
    driver = webdriver.Edge(options=opt, service=svc)
    driver.set_page_load_timeout(100000)

    driver.get('https://cas.dhu.edu.cn/identity/login?app=ehall')
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.XPATH, "/html/body/div[1]/div[2]/div[1]/div[2]/div[2]/div/div/div[4]/button")))
    driver.find_element(By.XPATH, '/html/body/div[1]/div[2]/div[1]/div[2]/div[2]/div/div/div[2]/div[1]/div/div[1]/div[2]/input').send_keys(username)
    driver.find_element(By.XPATH, '/html/body/div[1]/div[2]/div[1]/div[2]/div[2]/div/div/div[2]/div[2]/div/div[1]/div[2]/input').send_keys(password)
    driver.find_element(By.XPATH, '/html/body/div[1]/div[2]/div[1]/div[2]/div[2]/div/div/div[4]/button').click()
    wait.until(EC.presence_of_element_located((By.XPATH, "/html/body/div[1]/div[1]/div/div[1]/div[2]/img")))

    driver.get('https://jwgl.dhu.edu.cn/dhu/casLogin')
    wait.until(EC.presence_of_element_located((By.XPATH, "/html/body/div/div[1]/div/div[1]/span[3]/i")))

    cookies = {c['name']: c['value'] for c in driver.get_cookies()}
    driver.quit()

    jsessionid = cookies.get('JSESSIONID', '')
    vjuid = cookies.get('cookie_vjuid_portal_login', '')
    newjwgl = cookies.get('newjwgl', '')
    cookie_str = f"JSESSIONID={jsessionid}; zhilinDataTheme=default; cookie_vjuid_portal_login={vjuid}; newjwgl={newjwgl}"

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
    base = {
        "Host": "jwgl.dhu.edu.cn",
        "Connection": "keep-alive",
        "sec-ch-ua-platform": '"Windows"',
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": ua,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "sec-ch-ua-mobile": "?0",
        "Origin": "https://jwgl.dhu.edu.cn",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9,ar;q=0.8",
        "Cookie": cookie_str,
    }

    submit_h = {**base, "Content-Length": "31", "Referer": "https://jwgl.dhu.edu.cn/dhu/selectcourse/toSH"}
    query_h = {**base, "Content-Length": "503", "Referer": "https://jwgl.dhu.edu.cn/dhu/selectcourse/toSH"}
    public_h = {**base, "Content-Length": "21", "Referer": "https://jwgl.dhu.edu.cn/dhu/PublicQuery/toPage"}

    return submit_h, query_h, public_h
