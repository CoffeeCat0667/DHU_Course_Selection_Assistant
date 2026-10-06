# DHU 选课辅助工具

[![Stars](https://img.shields.io/github/stars/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&logo=github&label=Stars)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Last%20Commit)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/commits/main)
[![Issues](https://img.shields.io/github/issues/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Issues)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/issues)
[![Repo Size](https://img.shields.io/github/repo-size/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Size)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant)

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%206-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](https://opensource.org/license/mit)

东华大学（DHU）选课系统的 Windows 桌面辅助工具。

**Ver3.0** 已重构为单进程 PySide6 桌面应用：不再需要 Web 面板，也不再需要 Tkinter 配置器。

---

## 功能

| 模式 | 名称 | 行为 |
| --- | --- | --- |
| `Only_Submit` | 直接抢课 | 不查名额，直接多线程并发提交 |
| `FQTS` | 查询后抢课 | 先查名额，有余量再提交 |
| `FQTDLS` | 调课模式 | 退旧课后选新课，失败自动回滚 |

- 图形界面完成全部配置，无需手工编辑配置文件
- 实时监控：状态卡片（激活模式 / 当前状态 / 选课结果 / 已完成轮次 / 查询次数）+ 分级着色日志
- 登录失效后自动重新登录（进程内进行，连续失败 5 次则阻塞并提示，不再重启进程）
- 支持 HTTP 代理

---

## 环境要求

- Windows 10 / 11
- **Python 3.14**（开发环境为 3.14.8 64 位）
- **Microsoft Edge**：用于完成学校 CAS 登录，驱动由 Selenium Manager 自动匹配下载，无需手动安装 webdriver
- 能够访问 `jwgl.dhu.edu.cn` 的网络（校园网或学校 VPN）

---

## 安装

```powershell
python -m pip install -r requirements.txt
```

---

## 配置

### 方式一（推荐）

直接运行程序，在「配置」页填写后点「保存配置」。

### 方式二

```powershell
copy config.example.json config.json
```

然后手工编辑 `config.json`。

| 字段 | 说明 |
| --- | --- |
| `username` / `password` | 学号与密码 |
| `term_id` | 学期编号，见下方对照 |
| `active_mode` | 本次启用的模式，需与任务的 `mode` 一致 |
| `loop_interval` | 轮询间隔（秒），仅 FQTS / FQTDLS 模式生效 |
| `proxy` | 代理设置，`enabled: false` 时忽略 |
| `tasks[].mode` | 该任务的模式 |
| `tasks[].main_id` | 课程代码 |
| `tasks[].target_ids` | 目标教学班 ID，可填多个 |
| `tasks[].del_class_no` | 退课班号，仅 FQTDLS 模式需要 |
| `tasks[].del_raw_id` | 回滚 ID，仅 FQTDLS 模式需要 |

### 学期编号（term_id）

自 2026-2027 学年起：

| 学期 | term_id |
| --- | --- |
| 2026-2027 秋 | 86 |
| 2026-2027 春 | 87 |
| 2027-2028 秋 | 88 |
| 2027-2028 春 | 89 |
| …… | 每学期 +1 |

---

## 使用

```powershell
python main.py
```

1. 在「配置」页填写账号、学期、模式与任务，点「保存配置」
2. 点「开始抢课」（会自动切换到「监控」页）
3. `Only_Submit` 模式每完成一轮会等待确认，点「继续下一轮」继续
4. 随时可点「停止」中止

---

## 项目结构

```
main.py         唯一入口：Qt 界面（配置页 / 监控页）+ 抢课工作线程
state.py        线程安全的运行状态快照，供界面轮询
auth.py         Selenium 完成 CAS 登录，导出 Cookie
api.py          选课系统的 HTTP 调用
parser.py       解析接口返回的 HTML 片段
strategies.py   三种抢课模式的实现
loader.py       读取 config.json
config.json     本地配置文件
```

---

## Ver3.0 重构说明

- 移除 Flask 与 Web 监控面板，监控界面改为 Qt 原生实现
- 移除独立的 Tkinter 配置编辑器，配置界面并入 `main.py`
- 三个进程合并为单进程单窗口，标签页切换「配置 / 监控」
- 启动后需显式点击「开始抢课」才会运行
- 登录失败改为进程内重试，最多 5 次，超过则阻塞等待人工处理
- 界面使用 Qt 自带的 Windows 11 原生样式（浅色）

---

## 许可证

本项目基于 [MIT License](https://opensource.org/license/mit) 开源。
