# DHU 选课辅助工具

[![Stars](https://img.shields.io/github/stars/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&logo=github&label=Stars)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Last%20Commit)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/commits/main)
[![Issues](https://img.shields.io/github/issues/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Issues)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant/issues)
[![Repo Size](https://img.shields.io/github/repo-size/CoffeeCat0667/DHU_Course_Selection_Assistant?style=flat-square&label=Size)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant)

[![Version](https://img.shields.io/badge/Version-3.1-blue?style=flat-square)](https://github.com/CoffeeCat0667/DHU_Course_Selection_Assistant)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![PySide6](https://img.shields.io/badge/GUI-PySide6%206-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](https://opensource.org/license/mit)

东华大学（DHU）选课系统的 Windows 桌面辅助工具。

当前版本 **Ver3.1** —— 单进程 PySide6 桌面应用，不需要 Web 面板，也不需要 Tkinter 配置器。

---

## 功能

### 三个标签页

| 标签 | 内容 |
| --- | --- |
| **配置** | 账号信息（学号 / 密码 / 学期）+ 代理设置 |
| **选课** | 当前已选课程、总学分、当前课程表、应读未读课程 |
| **抢课** | 循环设置、激活模式、任务列表、实时监控与抢课控制 |

### 选课页

- **当前已选课程**：课程代码 / 课程名称 / 学分 / 课程类别 / 组班 / 任课教师，并汇总总学分
- **查看当前课程表**：**13 节 × 7 天**网格，每格标注课程名、上课周次（第 n-n 周）与上课地点，每门课一种底色
- **查看应读未读课程**：按课程类别分组（必修 / 选修），每个类别显示**要求学分 / 已修学分**；本学期已选的课程**黄色高亮**并标注「已选」
  - **双击任意课程**可查看该课程**本学期的开课情况**：所有教学班、任课教师、已录 ÷ 名额、上课周次、上课时间、上课地点
  - 该课程本学期不开课时显示 **「无 —— 本学期不开课」**

### 抢课页

| 模式 | 名称 | 行为 |
| --- | --- | --- |
| `Only_Submit` | 直接抢课 | 不查名额，直接多线程并发提交 |
| `FQTS` | 查询后抢课 | 先查名额，有余量再提交 |
| `FQTDLS` | 调课模式 | 退旧课后选新课，失败自动回滚 |

- 实时监控：状态卡片（激活模式 / 当前状态 / 选课结果 / 已完成轮次 / 查询次数）+ 分级着色日志
- 登录失效后自动重新登录（进程内进行，连续失败 5 次则阻塞并提示，不再重启进程）
- 可选 HTTP 代理

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
| 2026-2027 秋 | 88 |
| 2026-2027 春 | 89 |
| 2027-2028 秋 | 90 |
| 2027-2028 春 | 91 |
| …… | 每学期 +1 |

---

## 使用

```powershell
python main.py
```

1. 在「配置」页填写学号、密码、学期与代理设置，点「保存配置」
2. 点「开始运行」→ 程序登录并抓取数据，**自动切换到「选课」页**
3. 在「选课」页查看当前已选课程、总学分、当前课程表与应读未读课程
4. 切到「抢课」页配置循环间隔、激活模式与任务，点「开始抢课」
5. `Only_Submit` 模式每完成一轮会等待确认，点「继续下一轮」继续；随时可点「停止」中止

> 「保存配置」与「开始运行」只在「配置」页显示。

---

## 项目结构

```
main.py         唯一入口：Qt 界面（配置页 / 选课页 / 抢课页）+ 工作线程
state.py        线程安全的运行状态快照，供界面轮询
auth.py         Selenium 完成 CAS 登录，导出 Cookie
api.py          选课系统的 HTTP 调用
parser.py       解析接口返回的数据（已选课程 / 培养方案 / 教学班 / 课程表）
strategies.py   三种抢课模式的实现
loader.py       读取 config.json
config.json     本地配置文件
```

---

## 更新日志

### Ver3.1

- 界面改为**三标签**：配置 / 选课 / 抢课；「保存配置」「开始运行」仅在配置页显示
- 「开始运行」改为**登录并抓取数据后停留在「选课」页**，不再直接进入抢课循环
- 新增**当前已选课程**：数据来自 `initSelCourses`，含任课教师、组班序号、学分与总学分
- 新增**查看当前课程表**：13 节 × 7 天网格，标注上课周次与上课地点
- 新增**查看应读未读课程**：按课程类别分组，显示要求学分 / 已修学分；本学期已选课程黄色高亮
- 应读未读课程支持**双击查看本学期开课情况**（所有教学班与上课时间），本学期不开课时显示「无」
- 移除荣誉课程展示
- **修正 termId 基准为 88**（原按 86 计算会使公共查询接口返回空，并触发无限重新登录）

### Ver3.0

- 移除 Flask 与 Web 监控面板，监控界面改为 Qt 原生实现
- 移除独立的 Tkinter 配置编辑器，配置界面并入 `main.py`
- 三个进程合并为单进程单窗口
- 界面使用 Qt 自带的 Windows 11 原生样式（浅色）
- 登录失败改为进程内重试，最多 5 次，超过则阻塞等待人工处理

---

## 许可证

本项目基于 [MIT License](https://opensource.org/license/mit) 开源。
