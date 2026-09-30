# daily_checkin.py 开发文档

> 最后更新：2026-06-03  
> 状态：Refactored — 选择器已适配新版微软 Rewards DOM（Tailwind class 体系）

---

## 1. 项目概述

`daily_checkin.py` — 微软 Rewards 每日签到自动化脚本。使用 Playwright + Edge 浏览器，自动完成搜索积分、Daily Set 任务，以及 Earn 页面加分项和积分领取。

### 当前功能（v2.0）

| 阶段 | 功能 | 状态 |
|------|------|------|
| 1 | 加载 Bing 首页，多策略抓取热搜关键词 | ✅ 已实现 |
| 2 | 模拟搜索栏输入，完成 15 次搜索 | ✅ 已实现 |
| 3 | Daily Set 每日活动任务 | ✅ 已实现 |
| 4 | Earn 页面 +5/+10 加分项 | ✅ 已实现 |
| 5 | Dashboard 右上角侧边栏领取积分 | ✅ 已实现 |

---

## 2. 待开发功能

### 2.1 功能 A：Earn 页面自动完成加分项

#### 目标页面

`https://rewards.bing.com/earn`

#### 页面结构（已知模式）

```
rewards.bing.com/earn
├── offer 卡片列表（每个含积分值 +5/+10/+30）
│   ├── 搜索类：a[href*='bing.com/search?q=']
│   ├── 浏览类：a[href*='msn.com']
│   ├── 测验类：a[href*='quiz'] / a[href*='poll']
│   └── 共同点：子元素文本含 "+5"、"+10"
└── "更多活动" 折叠区域（需点击展开）
```

#### 处理流程

```
complete_earn_tasks(page, max_tasks=10):
  1. 导航到 https://rewards.bing.com/earn
  2. wait_for_selector(offers, timeout=25000)
  3. 查找全部可见 offer 卡片
  4. 过滤：仅保留含 "+5" / "+10" 文本的（轻量任务）
  5. 逐个点击 → 处理弹窗/新标签页 → 等待 5-8s → 关闭
  6. 点击"更多活动"展开 → 重复 3-5
  7. 返回成功完成数
```

#### 选择器备选链

```python
# offer 卡片
OFFER_SELECTORS = [
    "[data-bi-type='earn'] a",
    ".offer-card a[href]",
    ".earn-offer a[href]",
    ".ds-card a[href]",
    "mee-card a[href]",
    "li[role='listitem'] a",
    "#earn-section a[href*='bing.com']",
]

# 积分文本匹配
POINT_PATTERNS = ["+5", "+10", "+15", "+20"]

# "更多活动"展开按钮
MORE_ACTIVITIES_SELECTORS = [
    "text='More activities'",
    "text='更多活动'",
    "[aria-label*='More activities']",
    "[aria-label*='更多活动']",
    ".more-activities",
    "#moreActivities",
    "button:has-text('More')",
]
```

#### 边界处理

- offer 数量为 0 → 跳过，返回 0
- 点击后无弹窗 → 用 `page.expect_popup(timeout=5000)` 并捕获 TimeoutError
- 某些任务未登录不可用 → 跳过不可点击的卡片
- "更多活动"不存在 → 正常跳过第二层

---

### 2.2 功能 B：Dashboard 右上角侧边栏领取积分

#### 目标页面

`https://rewards.bing.com/dashboard`

#### 页面结构（已知模式）

```
rewards.bing.com/dashboard
├── 右上角积分状态区域
│   ├── #rewards-status / #rhs / .points-balance
│   └── 点击 → 触发右侧滑出面板
└── 右侧滑出侧边栏 (flyout/drawer)
    ├── 积分明细
    │   ├── 今日已赚取
    │   ├── 可领取积分 ← 目标
    │   └── 各来源统计
    └── 底部"领取积分"按钮
```

#### 处理流程

```
collect_redeemable_points(page):
  1. 确保已在 dashboard 页面
  2. 查找右上角积分/状态触发按钮 → 点击
  3. wait_for_selector(sidebar, timeout=10000)  等待滑出动画
  4. 等待 0.5s（动画缓冲）
  5. 在侧边栏中定位底部"领取积分"按钮 → 点击
  6. 等待确认反馈（2s）
  7. 关闭侧边栏（点击遮罩或再次点击触发按钮）
  8. 返回是否成功
```

#### 选择器备选链

```python
# 右上角触发按钮
STATUS_TRIGGER_SELECTORS = [
    "#rewards-status",
    ".rewards-status",
    "#rhs",
    ".points-balance",
    ".points-container",
    "[aria-label*='points']",
    "[aria-label*='积分']",
    "span:has-text('points')",
    "span:has-text('积分')",
]

# 侧边栏容器
SIDEBAR_SELECTORS = [
    ".flyout",
    ".drawer",
    "#pointsBreakdown",
    ".points-breakdown",
    ".point-breakdown",
    "[role='dialog']",
    ".right-rail",
    "#sidebar",
]

# 领取积分按钮
REDEEM_BUTTON_SELECTORS = [
    "text='领取积分'",
    "text='Redeem points'",
    "[aria-label*='Redeem']",
    "[aria-label*='领取']",
    "#redeemPoints",
    ".redeem-button",
    ".redeem",
    "button:has-text('Redeem')",
    "button:has-text('领取')",
]

# 关闭侧边栏（遮罩层）
SIDEBAR_CLOSE_SELECTORS = [
    ".mee-icon-Cancel",
    "[aria-label*='Close']",
    "[aria-label*='关闭']",
    ".flyout-close",
]
```

#### 边界处理

- 无待领取积分 → 跳过，返回 False
- 侧边栏未出现 → 等待超时后返回 False，不影响主流程
- 领取按钮不可点击 → 可能已领取，返回 False
- 关闭失败 → 尝试 ESC 键兜底：`page.keyboard.press("Escape")`

---

## 3. 集成方案

### 3.1 主流程调整

```python
def main():
    # ... 浏览器启动 ...

    # 阶段 1: 热搜关键词
    keywords = fetch_trending_keywords(page)

    # 阶段 2: 搜索加分
    search_ok = perform_searches(page, keywords)

    # 阶段 3: Earn 页面加分项  ← 新增
    earn_ok = complete_earn_tasks(page)

    # 阶段 4: Daily Set 每日活动
    daily_ok = complete_daily_set(page)

    # 阶段 5: 领取积分  ← 新增
    redeemed = collect_redeemable_points(page)

    # 汇总
    log.info(f"  搜索: {search_ok}/{SEARCH_COUNT}")
    log.info(f"  Earn 任务: {earn_ok} 个")
    log.info(f"  Daily Set: {daily_ok} 个")
    log.info(f"  领取积分: {'成功' if redeemed else '跳过/未找到'}")
```

### 3.2 执行顺序说明

1. **Earn 在 Daily Set 之前**：Earn 页面任务更轻量，先执行可避免 Daily Set 弹窗残留影响
2. **领取积分在最后**：确保所有积分都已记录后再领取
3. 每阶段独立容错：任一阶段失败不影响后续阶段

---

## 4. 通用辅助函数

### 4.1 选择器多重尝试

```python
def _try_click(page, selectors, timeout=5000):
    """按优先级尝试多个选择器，返回是否点击成功"""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            el.wait_for(state="visible", timeout=timeout)
            el.click()
            return True
        except Exception:
            continue
    return False
```

### 4.2 安全处理弹出新标签页

```python
def _safe_click_with_popup(page, element):
    """点击元素，安全处理弹出新标签页（或无弹窗情况）"""
    try:
        with page.expect_popup(timeout=8000) as popup_info:
            element.click()
        new_page = popup_info.value
        new_page.wait_for_load_state("domcontentloaded")
        time.sleep(random.randint(5, 8))
        new_page.close()
        return True
    except Exception:
        return False
```

---

## 5. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `daily_checkin.py` | 修改 | 新增 2 个函数 + 主流程集成 |
| `_old/daily_checkin.py` | 不动 | 原始 v1.0 备份 |

---

## 6. 验证步骤

```bash
# 1. 语法检查
python -m py_compile daily_checkin.py

# 2. 手动运行（首次建议 headless=False 观察）
python -u daily_checkin.py

# 3. 检查日志
# 确认日志中出现：
#   "正在处理 Earn 页面加分项..."
#   "正在尝试领取积分..."
# 以及成功/跳过提示
```

---

## 7. 已知风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 选择器不匹配 | 功能静默跳过 | 每个选择器链有多层 fallback；日志记录跳过原因 |
| 页面改版 | 部分选择器失效 | 需观察日志，必要时更新选择器 |
| 登录态过期 | 页面跳转到登录页 | wait_for_selector 超时 → 返回 0，不阻塞 |
| 已无待领取积分 | redeem 按钮不存在 | 正常返回 False，不报错 |
