import json
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
