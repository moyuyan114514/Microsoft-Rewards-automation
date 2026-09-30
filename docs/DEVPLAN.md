# 开发文档 — Microsoft Rewards Automation v2

> 最后更新：2026-09-30
> 状态：v2 稳定版 — 融合多项目反检测技术的重写版

---

## 1. 架构总览

### 1.1 三层架构

```
┌─────────────────────────────────────────────────────┐
│                  rewards_bot.py                      │
│  （业务层：流程编排 / 搜索策略 / 任务调度 / 配置）    │
├──────────────────────┬──────────────────────────────┤
│     browser.py       │        humanize.py           │
│  （浏览器驱动层）     │    （拟人行为模拟层）         │
│  引擎/通道/指纹      │    鼠标/键盘/滚动            │
├──────────────────────┴──────────────────────────────┤
│            Patchright / Playwright                  │
│         （底层浏览器自动化引擎）                     │
└─────────────────────────────────────────────────────┘
```

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **一致性优先** | 反检测的核心是"自洽"——UA、视口、像素比、触摸必须成套改，单改任何一项都更可疑 |
| **不完美拟人** | 真人不会每天刷满、不会准点运行、不会百发百中——故意引入波动才更真实 |
| **优雅降级** | 引擎、浏览器通道、积分接口、选择器，每一层都有回退，任一层失效不影响整体运行 |
| **静默等待** | 登录检测不刷新页面干扰用户，只被动观察 URL 变化 |

---

## 2. 核心模块详解

### 2.1 browser.py — 浏览器驱动层

#### 引擎优先级

```
patchright（首选，反检测最强）
  └→ 失败 → playwright（回退）
```

Patchright 是 Playwright 的补丁版，剥离了 `Runtime.enable` 等运行时注入痕迹。
微软的自动化检测高度依赖这些痕迹。

#### 通道优先级（每个引擎内）

| 引擎 | 通道顺序 | 原因 |
|------|----------|------|
| patchright | 内置 Chromium → Edge → Chrome | patchright + 系统 Edge 在 rewards 页有已知崩溃 bug（playwright#41438） |
| playwright | Edge → Chrome → 内置 Chromium | 原生 playwright 无此问题，系统浏览器指纹更真实 |

#### 隐身启动参数

```python
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",  # 移除 navigator.webdriver
    "--no-first-run",
    "--no-default-browser-check",
    "--mute-audio",
    "--disable-dev-shm-usage",
    "--start-maximized",
]
```

#### 移动端指纹一致性

移动端仿真必须同时设置以下参数，缺一会被识破：

```python
viewport={"width": 412, "height": 915},   # iPhone 14 视口
device_scale_factor=3,                     # 像素比
is_mobile=True,
has_touch=True,
user_agent=MOBILE_USER_AGENT,              # iPhone Safari UA
```

### 2.2 humanize.py — 拟人行为模拟层

#### 鼠标轨迹算法

使用**二次贝塞尔曲线** + **smoothstep 缓动**模拟真人运鼠：

```
起点 ────(控制点)──→ 终点
      贝塞尔曲线
```

- **控制点**：在连线中点附近随机偏移，偏移量 = `max(20, min(150, dist * 0.35))`
- **缓动**：`_smoothstep(t) = t² × (3 - 2t)` — 起步慢 → 中间快 → 收尾慢
- **步数**：距离越远步数越多，`steps = clamp(dist / rand(8,15), 8, 45)`
- **微抖动**：每步 ±2px 随机偏移（终点除外）
- **变速停顿**：起步段快、中段慢、收尾最从容；5% 概率额外犹豫

#### 点偏修正机制

5% 概率先点偏 30px 以内，再快速修正回来——模拟真人运鼠的典型失误模式。

#### 点击验证（click_verified）

陷阱：贝塞尔滑行需要 1~3 秒，期间页面 hover 动画可能移动布局，盲目点击会点空。

解决方案：按下前用 `document.elementFromPoint(x, y)` 与目标元素做身份比对（目标本身或其子元素才算命中），未命中则重新瞄准，重试耗尽后回退 `locator.click()`。

#### 拟人滚动

- 用 `mouse.wheel()` 发真实滚轮事件（小步快频，每步 30~80px）
- 深度分布：70% 浅层浏览（页面 10%~50%），30% 滚近底部
- 滚动后有"阅读停顿"

#### 逐键输入

- 每键 40~110ms 随机间隔
- 3% 概率词级停顿（卡壳）
- 对照 `fill()` 是瞬间填充，无任何中间按键事件

### 2.3 rewards_bot.py — 业务编排层

#### 配置合并

`deep_merge(base, override)` 递归合并，用户配置只需覆盖想改的键，缺失自动回落到 `DEFAULT_CONFIG`。

#### humanize 门禁

```
启动 → 静默时段？ → 是 → 等待到时段结束
     → 当天已完成？→ 是 → 直接退出
     → 启动抖动？ → 是 → 随机等待
     → 进入主流程
```

- **静默时段**：支持跨午夜、按星期指定
- **当天完成**：成功运行后写入 `logs/last-success.txt`，下次启动检查
- **启动抖动**：`startJitterSec` 区间内随机延迟，避免计划任务准点

#### 搜索会话（积分驱动）

```
目标次数 = 设定次数 × 随机比例（searchTargetRatio）
每 N 次核对积分 → 有增长 → 清零停滞计数
                  无增长 → 停滞计数 +1
                            连续 stagnantBatches 次零增长 → 提前收手
```

核心思路：不追求搜满固定次数，积分停涨就收手，更像真人行为。

#### 任务系统

| 任务类型 | 函数 | 页面 | 策略 |
|----------|------|------|------|
| Daily Set | `complete_daily_set()` | Dashboard | 点击所有搜索类任务卡片 |
| Earn 简单任务 | `complete_earn_tasks()` | Earn | 逐个点击简单任务（搜索/浏览类） |
| Earn Punchcard | `complete_earn_tasks()` 内 | Earn/Quest | 进入子页面逐个点 CTA |
| 领取积分 | `collect_redeemable_points()` | Dashboard | 找到"可领取"卡片并点击 |

任务点击兼容三种打开方式：
1. **popup** — 新标签页（主流）→ 停留后关闭
2. **same-tab** — 当前页跳转 → 后退返回
3. **none** — 无导航（任务可能已完成）

---

## 3. 选择器维护指南

### 3.1 选择器位置速查

所有选择器常量集中在 `rewards_bot.py` 文件顶部的 `# ── 常量 ──` 区域：

| 常量名 | 用途 | 当前值 |
|--------|------|--------|
| `BING_HOME` | Bing 首页 URL | `https://cn.bing.com` |
| `DASHBOARD_URL` | Dashboard 页 | `https://rewards.bing.com/dashboard` |
| `EARN_URL` | Earn 页 | `https://rewards.bing.com/earn` |
| `POINTS_API` | 积分查询接口 | `.../api/getuserinfo?type=1` |
| `SEARCH_BOX` | 搜索框 | `#sb_form_q` |
| `RESULT_LINK` | 搜索结果标题 | `#b_results .b_algo h2` |
| `TRENDING_SELECTORS` | 热搜抓取（列表） | 12 个备选选择器 |
| `LOGIN_INDICATORS` | 登录态检测（列表） | 5 个备选选择器 |
| `EARN_SIMPLE_TASK_SELECTORS` | Earn 简单任务（列表） | 3 个备选选择器 |
| `EARN_PUNCHCARD_SELECTOR` | Earn Punchcard 入口 | `a[href*='/earn/quest/']` |
| `EARN_CTA_SELECTOR` | Punchcard 内 CTA | `a[aria-label][href*='search?q=']:not([aria-disabled='true'])` |
| `REDEEMABLE_LABEL_SELECTOR` | 可领取积分标签 | `p.text-labelControl:has-text('可领取')` |
| `REDEEMABLE_AMOUNT_SELECTOR` | 可领取积分数值 | `p.text-pageHeader` |

### 3.2 页面改版适配流程

当某个功能突然不工作（日志显示"0 个任务"或"未找到"）：

1. **确认是选择器问题**
   ```
   检查日志：是否有选择器相关报错？
   手动打开页面：元素是否还在？class/id 是否变了？
   ```

2. **扫描当前 DOM**
   ```bash
   # 扫描对应页面
   python tools/scan_dashboard_dom.py   # Dashboard
   python tools/scan_earn_dom.py       # Earn
   python tools/scan_quest_dom.py      # Quest/Punchcard
   python tools/scan_rewards_page.py   # Rewards 通用
   ```

3. **更新选择器**
   - 找到新的稳定选择器（优先用 `id`、`aria-label`、`href` 模式）
   - 在对应常量列表中**追加**新选择器（不要删除旧的，保留向后兼容）
   - 按优先级排序，最可靠的放前面

4. **冒烟验证**
   ```bash
   python rewards_bot.py --config config.smoke.json
   ```

### 3.3 选择器编写最佳实践

- **优先使用语义化属性**：`aria-label`、`role`、`href` 模式比 class 更稳定
- **避开 Tailwind class**：Rewards 大量使用 Tailwind，class 名可能随构建变化
- **多选择器 fallback**：每个功能都准备 3~5 个备选选择器
- **用 `:has-text()` 定位文本**：Playwright 支持，比纯文本匹配更可靠
- **避开动态 id**：形如 `:Rxxx:` 的 React 生成 id 不要用

---

## 4. 调试与排错

### 4.1 日志说明

日志系统使用 Python `logging` 模块，双输出：

| 输出 | 级别 | 位置 |
|------|------|------|
| 控制台 | INFO | 实时观察进度 |
| 文件 | DEBUG | `logs/rewards_bot.log` |

文件日志支持 2MB 轮转，保留 5 份（`.log` → `.log.1` → ... → `.log.4`）。

日志格式：`时间 | 级别 | 消息`

关键日志标记：
- `[PC n/m]` — PC 搜索进度
- `[MOBILE n/m]` — 移动端搜索进度
- `✓` — 任务成功
- `积分 +x → y` — 积分增长确认
- `积分无增长 (n/m)` — 停滞计数

### 4.2 常见问题排查

#### 浏览器启动失败

```
症状：RuntimeError: 所有浏览器通道均无法启动
排查：
  1. 是否已安装 Edge 或 Chrome？
  2. patchright/playwright 是否已安装？
     pip list | grep patchright
     pip list | grep playwright
  3. 尝试安装内置 Chromium：
     patchright install chromium
     # 或
     playwright install chromium
```

#### 登录态检测不到

```
症状：脚本始终说"未登录"，但浏览器里明明登录了
原因：LOGIN_INDICATORS 中的选择器全部失效
解决：
  1. 手动在 Dashboard 页检查元素
  2. 更新 LOGIN_INDICATORS 常量
  3. 也可能是页面还在加载中，增加等待时间
```

#### 搜索积分不涨

```
可能原因：
  1. 今日搜索积分已达上限（PC 30 次 / 移动 20 次后通常满）
  2. POINTS_API 接口变更，积分读取失败（此时走固定次数）
  3. 登录态失效，搜索未被计入
排查：
  - 查看日志中"积分"相关行
  - 手动刷新 rewards.bing.com 看积分是否变化
```

#### 任务点击无反应

```
可能原因：
  1. 选择器定位了已完成的任务（已完成的任务不可点击）
  2. 元素被遮挡（弹窗、遮罩层）
  3. 页面改版，href 模式变化
排查：
  - 用 tools/scan_earn_dom.py 扫描当前页面
  - 在浏览器 DevTools 中检查目标元素的 class/href
```

### 4.3 冒烟测试配置

`config.smoke.json` 是用于快速验证的精简配置：

- 搜索次数：3 次（默认 30）
- 搜索间隔：2~4 秒（默认 8~20 秒）
- 最大任务数：3 个（默认 10）
- 登录超时：6 分钟（默认 10 分钟）
- 完成后自动退出

用途：
- 验证页面改版后选择器是否正常
- 快速测试新功能
- CI/CD 集成测试

---

## 5. 扩展开发

### 5.1 添加新任务类型

**步骤：**

1. 在 `rewards_bot.py` 中新增函数
   ```python
   def complete_new_feature(page, human: Human) -> int:
       """新任务说明"""
       log.info("正在处理 XXX...")
       if not safe_goto(page, TARGET_URL):
           return 0
       # ... 具体逻辑 ...
       return done_count
   ```

2. 在 `DEFAULT_CONFIG["tasks"]` 加开关
   ```python
   "tasks": {
       ...
       "newFeature": True,
   }
   ```

3. 在 `main()` 的任务阶段调用
   ```python
   new_done = complete_new_feature(page, human) if tasks_cfg["newFeature"] else 0
   ```

4. 更新汇总输出
   ```python
   log.info(f"  新任务: {new_done}")
   ```

5. 在 `config.json` 和 `README.md` 中补充说明

### 5.2 添加新的拟人行为

在 `humanize.py` 的 `Human` 类中添加方法，遵循以下原则：

- 方法命名用动词短语（`drag_to`、`double_click`、`pinch_zoom` 等）
- 所有坐标操作使用视口 client 坐标
- 失败时回退到 Playwright 原生方法（保持可用性）
- 添加随机变化，避免完全可预测

### 5.3 配置项添加

1. 在 `DEFAULT_CONFIG` 中添加默认值
2. 在 `config.json` 中添加示例值
3. 在 `README.md` 配置表中补充说明
4. 使用方通过 `cfg["section"]["key"]` 读取

---

## 6. 安全与合规

### 6.1 敏感信息保护

| 数据 | 位置 | 是否入库 |
|------|------|----------|
| 浏览器 Profile（含 Cookie） | `edge_profile/` | ❌ `.gitignore` 排除 |
| 移动端 Profile | `edge_profile_mobile/` | ❌ `.gitignore` 排除 |
| 运行日志 | `logs/` | ❌ `.gitignore` 排除 |
| 配置文件 | `config.json` | ✅ 不含敏感信息 |

### 6.2 风险提示

- 自动化违反微软 Rewards 服务条款，有封号风险
- 拟人化只能降低概率，不能完全消除风险
- 建议：住宅 IP + 有界面模式 + 拟人化全开 + 不刷满目标
- 数据中心 IP + headless 模式风险极高

---

## 7. 文件清单

| 文件 | 行数（约） | 职责 |
|------|-----------|------|
| `rewards_bot.py` | 870 | 主入口，流程编排 |
| `browser.py` | 128 | 浏览器启动层 |
| `humanize.py` | 221 | 拟人行为模拟 |
| `config.json` | 37 | 运行配置 |
| `config.smoke.json` | 37 | 冒烟测试配置 |
| `requirements.txt` | 2 | 依赖 |
| `daily_checkin.py` | - | v1 旧版（参考） |
| `tools/scan_*.py` | 5 × ~100 | DOM 扫描工具 |
| `scripts/*.py` | - | 旧版脚本（参考） |
| `docs/DEVPLAN.md` | - | 本文档 |
| `README.md` | - | 用户文档 |

---

## 8. 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v2.0 | 2026-09 | 融合重写版：Patchright + 拟人化 + 积分驱动搜索 + 全任务覆盖 |
| v1.0 | 2026-06 | 初版：Playwright + 基础搜索 + Daily Set |
