# Microsoft Rewards 每日签到自动化 v2

> 基于浏览器自动化的微软 Rewards 签到脚本。融合多个开源项目的反检测与拟人化技术，
> 只专注微软 Rewards；自动完成搜索积分、Daily Set、Earn 加分项及积分领取。

---

## 致谢与技术来源

本项目的拟人化与反检测设计研读并参考了以下开源项目，在此致谢：

| 项目 | 借鉴内容 |
|------|----------|
| [TheNetsky/Microsoft-Rewards-Script](https://github.com/TheNetsky/Microsoft-Rewards-Script)（TypeScript，~1.1k★） | Patchright 引擎选型；积分目标驱动搜索（停涨即止）；"不完美"拟人策略（随机不刷满目标 searchTargetRatio、静默时段 quietHours、当天完成不重跑、启动时刻抖动）；搜索后随机滚动/随机点击结果 |
| [chiihero/Microsoft-Rewards-Script](https://github.com/chiihero/Microsoft-Rewards-Script)（中文本地化，467★） | 中文环境的整体思路与配置化设计参考 |
| [safarsin/AutoRewarder](https://github.com/safarsin/AutoRewarder)（Python，338★） | `humanize.py` 的核心算法全部源自对其 `src/emulator/human.py` 的研读：二次贝塞尔鼠标轨迹 + smoothstep 缓动、±2px 微抖动、小概率点偏后修正、元素内随机落点、70/30 滚动深度分布、移动端 UA/触摸全套仿真 |
| [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) | Playwright 的补丁版，剥离运行时注入痕迹，反检测能力的关键 |
| [ghost-cursor](https://github.com/Xetera/ghost-cursor) | 贝塞尔轨迹鼠标模拟的思路来源（MSRS 使用，本项目用 Playwright 原生事件自实现） |

反检测原理简述：伪装成正常用户 = **一致性 + 自然性**。浏览器层不露自动化痕迹（Patchright +
`--disable-blink-features=AutomationControlled`）、指纹层自洽（UA/视口/触摸/像素比成套改）、
行为层自然（贝塞尔鼠标、逐键输入、拟人滚动）、数据层不完美（随机不刷满、作息随机化）。

---

## 功能特性

- **反检测引擎** — Patchright 优先（未安装自动回退 Playwright），浏览器通道 Edge → Chrome → 内置 Chromium 依次回退
- **拟人行为层** — 贝塞尔曲线鼠标轨迹、逐键随机间隔输入、真实滚轮拟人滚动、5% 概率点偏自修正
- **积分驱动搜索** — 定期核对积分增量，停涨自动收手；每天随机不刷满目标（可配）
- **热搜关键词抓取** — Bing 首页多选择器抓取 + 50+ 内置词库兜底
- **任务全覆盖** — Daily Set、Earn 简单任务、Punchcard 子任务、Dashboard 积分领取
- **humanize 门禁** — 静默时段、当天完成跳过、启动随机延迟（挂计划任务必备）
- **移动端搜索（可选）** — 独立 Profile + iPhone 形态上下文（UA/视口/触摸全套一致）
- **完整日志** — 文件轮转 + 控制台实时输出

---

## 快速开始

### 前置要求

- Python 3.10+
- Microsoft Edge 或 Google Chrome（或 Playwright/Patchright 内置 Chromium）

### 安装

```bash
pip install -r requirements.txt

# 安装补丁版 Chromium（使用系统已安装的 Edge/Chrome 可跳过）
patchright install chromium
# 若未安装 patchright，用: playwright install chromium
```

### 首次运行（登录）

```bash
python rewards_bot.py
```

首次运行会弹出浏览器窗口。若未登录会自动提示并等待你在窗口中登录
（rewards.bing.com），登录态保存在 `edge_profile/`，之后免登录。
移动端搜索开启后同理，首次需在移动端窗口登录一次。

### 日常运行

```bash
python rewards_bot.py                     # 跑完保持浏览器开启（默认）
python rewards_bot.py --exit-when-done    # 跑完自动退出，适合计划任务
python rewards_bot.py --config my.json    # 指定配置文件
```

---

## 配置说明（config.json）

所有项都有默认值，缺失的键自动回落到内置默认，只需覆盖想改的：

| 键 | 默认 | 说明 |
|----|------|------|
| `humanize.enabled` | `true` | 拟人化总开关 |
| `humanize.quietHours` | `[]` | 静默时段，如 `[{"days":["mon","tue"],"start":"02:30","end":"07:30"}]`，运行落入时段会挂起等待 |
| `humanize.skipWhenCompletedToday` | `false` | 当天已成功完成则直接退出（计划任务建议开启） |
| `humanize.startJitterSec` | `[0, 0]` | 启动随机延迟区间（秒），避免每天准点跑；计划任务建议 `[0, 600]` |
| `humanize.searchTargetRatio` | `[0.85, 1.0]` | 每天随机完成搜索目标的比例——**故意不刷满**，统计上更像真人 |
| `humanize.typingDelayMs` | `[40, 110]` | 每键输入间隔 |
| `humanize.missProb` | `0.05` | 鼠标点击"点偏"概率（点偏后自动修正） |
| `search.desktopCount` | `30` | PC 搜索目标次数 |
| `search.intervalSec` | `[8, 20]` | 搜索间隔，另有 5% 概率额外"走神" 20~60s |
| `search.searchRefreshEvery` | `8` | 每搜 N 次回一次 Bing 首页 |
| `search.stagnantBatches` | `2` | 连续 N 次核对积分无增长 → 提前结束搜索 |
| `search.pointsCheckEvery` | `5` | 每搜 N 次核对一次积分 |
| `search.randomScrollProb` | `0.6` | 搜索后随机滚动概率 |
| `search.randomClickProb` | `0.3` | 搜索后随机点击结果概率 |
| `tasks.*` | `true` | dailySet / earn / punchcard / redeem 各任务开关 |
| `tasks.maxTasks` | `10` | Earn 页面最多处理的任务数 |
| `mobile.enabled` | `false` | 移动端搜索（独立 Profile，需登录一次）。注意：微软登录页在移动端仿真下可能异常 |
| `runtime.loginTimeoutMin` | `10` | 等待手动登录的最长分钟数 |
| `runtime.exitWhenDone` | `false` | 完成后自动退出（`--exit-when-done` 可覆盖） |

---

## 架构概览

```
                    ┌─────────────────────┐
                    │   rewards_bot.py    │
                    │    （主流程编排）    │
                    └─────────┬───────────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
  ┌────────▼──────┐  ┌────────▼──────┐  ┌──────▼────────┐
  │  browser.py   │  │  humanize.py  │  │  任务选择器    │
  │ （浏览器层）   │  │ （拟人行为层） │  │ （搜索/任务）  │
  └────────┬──────┘  └───────────────┘  └───────────────┘
           │
  ┌────────▼──────┐
  │ Patchright /  │
  │ Playwright    │
  └───────────────┘
```

### 核心模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **主入口** | `rewards_bot.py` | 流程编排、配置加载、搜索会话、任务调度、日志系统 |
| **浏览器层** | `browser.py` | 引擎选择（Patchright→Playwright）、通道回退（Edge→Chrome→Chromium）、隐身参数、移动端指纹 |
| **拟人层** | `humanize.py` | 贝塞尔鼠标轨迹、逐键输入、拟人滚动、点偏修正 |
| **DOM 扫描工具** | `tools/` | 页面改版时分析 DOM 结构，辅助更新选择器 |
| **旧版脚本** | `daily_checkin.py` / `scripts/` | v1 遗留，保留作参考 |

### 主流程顺序

```
启动 → humanize 门禁（静默/已完成/抖动）
  → 启动浏览器 + 确保登录
  → 阶段 1: PC 搜索（积分驱动，停涨即止）
  → 阶段 2: 移动端搜索（可选，独立 Profile）
  → 阶段 3: Daily Set 任务
  → 阶段 4: Earn 页面任务（含 Punchcard）
  → 阶段 5: 领取可领取积分
  → 汇总 → 保持浏览器 / 退出
```

---

## 开发指南

### 目录结构

```
microsoft-rewards-automation/
├── rewards_bot.py             # 主脚本：编排 + 搜索策略 + 任务选择器（核心入口）
├── browser.py                 # 浏览器启动层：Patchright/Playwright + 通道回退 + 隐身参数
├── humanize.py                # 拟人行为层：贝塞尔鼠标 / 逐键输入 / 拟人滚动
├── config.json                # 运行配置（均有默认值，可部分覆盖）
├── config.smoke.json          # 冒烟测试配置（减少次数，快速验证）
├── requirements.txt
├── daily_checkin.py           # [旧版] v1 单文件脚本，保留作参考
├── scripts/                   # 旧版辅助脚本
├── tools/                     # DOM 扫描工具（页面改版时用于适配选择器）
├── docs/DEVPLAN.md            # 开发文档与维护指南
└── logs/                      # 运行日志（.gitignore）
```

### 调试技巧

1. **冒烟测试**：用 `config.smoke.json` 快速验证整体流程
   ```bash
   python rewards_bot.py --config config.smoke.json
   ```

2. **查看详细日志**：日志文件在 `logs/rewards_bot.log`，支持 2MB 轮转、保留 5 份

3. **选择器失效排查**：页面改版后用 `tools/` 下的扫描工具分析当前 DOM
   ```bash
   python tools/scan_dashboard_dom.py    # 扫描 Dashboard 页
   python tools/scan_earn_dom.py        # 扫描 Earn 页
   python tools/scan_quest_dom.py       # 扫描 Quest/Punchcard 页
   ```

4. **积分接口不可用**：`POINTS_API` 可能失效，此时脚本自动退化为固定次数搜索，
   日志中会有"积分读取不可用"提示

### 页面改版适配流程

当 Rewards 页面改版导致选择器失效时：

1. 运行对应 `tools/scan_*.py` 扫描当前 DOM 结构
2. 在 `rewards_bot.py` 中找到对应选择器常量（文件顶部 `# ── 常量 ──` 区域）
3. 更新选择器或增加新的备选选择器
4. 用 `config.smoke.json` 冒烟验证

关键选择器位置一览：

| 功能 | 常量 / 变量 | 文件位置 |
|------|------------|----------|
| 搜索框 | `SEARCH_BOX` | rewards_bot.py 顶部 |
| 搜索结果链接 | `RESULT_LINK` | rewards_bot.py 顶部 |
| 热搜抓取 | `TRENDING_SELECTORS` | rewards_bot.py 顶部 |
| 登录检测 | `LOGIN_INDICATORS` | rewards_bot.py 顶部 |
| Daily Set 任务 | `#dailyset a[href*='search?q=']` | `complete_daily_set()` 内 |
| Earn 简单任务 | `EARN_SIMPLE_TASK_SELECTORS` | rewards_bot.py 顶部 |
| Earn Punchcard | `EARN_PUNCHCARD_SELECTOR` | rewards_bot.py 顶部 |
| Earn CTA | `EARN_CTA_SELECTOR` | rewards_bot.py 顶部 |
| 可领取积分 | `REDEEMABLE_LABEL_SELECTOR` | rewards_bot.py 顶部 |

### 添加新任务类型

1. 在 `rewards_bot.py` 中新增 `complete_xxx()` 函数
2. 在 `main()` 的"阶段 3: 任务"部分调用
3. 在 `config.json` 的 `tasks` 段加开关
4. 在 `DEFAULT_CONFIG` 中补充默认值

---

## 在哪里运行：电脑还是服务器？

参考的几个项目两种都支持，各有代价：

| 方式 | 做法 | 风控视角 |
|------|------|----------|
| **家用电脑（推荐）** | 直接 `python rewards_bot.py --exit-when-done` + Windows 计划任务 | 住宅 IP + 真实浏览器环境，最接近"正常用户" |
| **服务器** | MSRS/chiihero 版提供 Docker + 内置 cron；本项目同样可跑（Linux 装 Chromium） | 数据中心 IP 是显著风险信号，且服务器常需 headless（Rewards 会检测），封号概率明显更高 |

结论：**这类脚本优先在家里跑**。如果一定要服务器，选离账号地区近的、可长期不变的 IP，
并接受更高风险。

### Windows 计划任务设置

1. 打开「任务计划程序」→ 创建基本任务
2. 触发器：每天，选一个你通常醒着的时间段（比如 09:00）
3. 操作：启动程序
   - 程序：`pythonw.exe`（无窗口运行）或 `python.exe`
   - 参数：`rewards_bot.py --exit-when-done`
   - 起始于：项目目录
4. 建议配合 `config.json` 开启：
   - `skipWhenCompletedToday: true` — 防止重复运行
   - `startJitterSec: [0, 600]` — 0~10 分钟随机延迟，避免准点

---

## 注意事项

- **不可 headless** — Rewards 检测无头浏览器，脚本强制有界面模式
- **不要分享 Profile 目录** — 含登录 Cookie，已加入 `.gitignore`
- **页面改版** — 用 `tools/` 下扫描工具分析新 DOM，更新 `rewards_bot.py` 中的选择器常量
- **风险自负** — 自动化违反微软 Rewards 服务条款，有封号风险；拟人化只能降低概率，不能消除
- **非中国区** — 把 `rewards_bot.py` 里的 `BING_HOME` 改为所在地区 Bing 域名
- **移动端登录问题** — 微软登录页在移动端仿真下可能跳转异常，若遇此情况请保持 `mobile.enabled: false`

---

## 常见问题

**Q: 首次运行提示登录，但窗口一直停在登录页？**
A: 请在弹出的浏览器窗口中手动完成登录。脚本不会刷新页面干扰你，登录成功后自动继续。
如果等待超时（默认 10 分钟），检查是否卡在了二次验证步骤。

**Q: 搜索了很多次但积分没涨？**
A: 可能原因：1) 搜索端已达今日上限；2) 登录态失效；3) 积分 API 暂时不可用。
查看日志中"积分"相关行，确认是接口问题还是实际无增长。

**Q: 如何确认用的是 Patchright 还是 Playwright？**
A: 日志第一行浏览器启动信息会标明 `(patchright / xxx)` 或 `(playwright / xxx)`。
Patchright 优先，未安装才回退到 Playwright。

**Q: 任务完成数比预期少？**
A: 正常现象。脚本只处理"看起来可点击"的任务，已完成的、需要复杂交互的（如测验）会自动跳过。

---

## 许可

[MIT License](LICENSE)
