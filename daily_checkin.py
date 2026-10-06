"""
daily_checkin.py —— 微软 Rewards 每日签到统一脚本
功能：
  1. 自动获取热搜关键词（Bing 多策略抓取 + 内置关键词库兜底）
  2. 自动搜索 15 个关键词赚取搜索积分（模拟搜索栏输入）
  3. 完成 Daily Set 每日活动任务
  4. 日志记录（文件 + 控制台）

用法：
  python -u daily_checkin.py              # 签到后保持浏览器开启（默认）
  python -u daily_checkin.py --exit-when-done   # 签到完成后自动退出（适合计划任务）
"""

import os
import sys
import time
import random
import logging
import re
import argparse
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from playwright.sync_api import sync_playwright, Page

# ── 编码兼容 ──────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="ignore")

# ── 配置常量 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent

# Profile 目录（用于持久化登录态，首次运行需手动创建或通过 connect_test.py 生成）
PROFILE_DIR = str(SCRIPT_DIR / "edge_profile")

# 浏览器通道（按优先级尝试，可在不同操作系统上兼容）
#   "msedge" → 系统安装的 Microsoft Edge（Windows 默认）
#   "chrome" → 系统安装的 Google Chrome
#   None     → Playwright 内置 Chromium（最通用，但需要先 playwright install chromium）
BROWSER_CHANNELS = ["msedge", "chrome", None]

LOG_DIR = SCRIPT_DIR / "logs"                              # 日志目录
LOG_FILE = LOG_DIR / "checkin.log"                         # 日志文件
SEARCH_COUNT = 15                                          # 每次搜索关键词数量
SEARCH_INTERVAL_MIN = 4                                    # 搜索间隔最小值（秒）
SEARCH_INTERVAL_MAX = 7                                    # 搜索间隔最大值（秒）
BING_HOME = "https://cn.bing.com"                          # Bing 首页
DASHBOARD_URL = "https://rewards.bing.com/dashboard"       # Rewards 控制面板
EARN_URL = "https://rewards.bing.com/earn"                  # Earn 页面


# ── 日志系统 ──────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    """配置双通道日志：文件（轮转）+ 控制台"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("daily_checkin")
    logger.setLevel(logging.DEBUG)

    # 文件 handler（轮转：单文件最大 2MB，保留 5 个备份）
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S"
    ))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = setup_logging()


# ── 热搜关键词库（内置备选，50+ 覆盖多领域） ─────────────
HOT_KEYWORDS_BACKUP = [
    # 科技
    "人工智能最新进展", "ChatGPT 更新", "苹果新品发布", "iPhone 最新消息",
    "华为 Mate 系列", "特斯拉新车型", "量子计算突破", "5G 应用场景",
    "元宇宙发展", "区块链技术",
    # 财经
    "股市行情", "比特币价格", "美联储利率", "人民币汇率",
    "房价走势", "新能源车补贴",
    # 体育
    "世界杯", "NBA 季后赛", "英超联赛", "欧冠决赛",
    "奥运会", "F1 赛事",
    # 娱乐
    "热门电影推荐", "豆瓣高分", "综艺节目", "热门歌曲",
    "明星动态", "演唱会",
    # 生活
    "天气预报", "旅游景点推荐", "美食做法", "减肥方法",
    "健康养生", "家居装修",
    # 教育
    "高考", "考研", "留学申请", "编程学习",
    "英语学习", "在线课程",
    # 社会
    "今日新闻", "国际形势", "环保政策", "交通出行",
    "疫情防控", "教育改革",
    # 趣味
    "冷知识", "奇闻趣事", "历史故事", "科幻小说",
    "宇宙探索", "海洋生物",
]

# ── 无关词过滤表 ─────────────────────────────────────────
SKIP_PATTERNS = [
    "热点", "翻译", "顺流", "必应", "Bing", "bing",
    "奥基乔比", "苏必利尔", "庞恰特雷恩",
]

# ── 热搜关键词抓取选择器 ─────────────────────────────────
# 第一层主抓取：按优先级尝试 Bing 首页热搜区域常见选择器
TRENDING_SELECTORS_LAYER1 = [
    "#trending a[href*='search']",
    "#sc_hdu a[href*='search']",
    ".hp_sw_trend a",
    "#hp_sw_trend a",
    ".vs_sw_trend a",
    "a[href*='search?q=']",
    ".hp_tile a[href*='search']",
    ".cardNews a[href*='search']",
]

# 第二层补抓取：滚动页面后再尝试的选择器
TRENDING_SELECTORS_LAYER2 = [
    ".content a[href*='search']",
    "a[href*='q=']",
    "[data-trending] a",
    ".ntc_cl_c a",
]


# ── 热搜关键词获取 ────────────────────────────────────────
def _extract_keywords_from_elements(page: Page, selector: str, seen: set) -> list[str]:
    """从页面中给定选择器匹配的元素中提取关键词文本"""
    result = []
    try:
        elements = page.locator(selector).all()
        for el in elements:
            try:
                if not el.is_visible():
                    continue
                text = el.inner_text().strip()
                if not text or len(text) < 2:
                    continue
                # 清理数字前缀（如 "1诺基亚…" → "诺基亚…"）
                cleaned = re.sub(r"^[0-9A-Z]\s*", "", text)
                # 过滤无关标签
                if any(p in cleaned for p in SKIP_PATTERNS):
                    continue
                if cleaned not in seen and len(cleaned) >= 3:
                    seen.add(cleaned)
                    result.append(cleaned)
            except Exception:
                continue
    except Exception:
        pass
    return result


def fetch_trending_keywords(page: Page, count: int = SEARCH_COUNT) -> list[str]:
    """
    从 Bing 首页多策略抓取热搜关键词。
    三层保障：
      第一层 —— 主抓取（多个选择器遍历）
      第二层 —— 滚动触发懒加载后补抓取
      第三层 —— 仅当完全失败时才启用内置词库兜底
    内置词库绝不用于"数量补齐"，只用于"全失败兜底"。

    Args:
        page: Playwright Page 对象（需已加载 Bing 首页）
        count: 需要获取的关键词总数

    Returns:
        去重后随机打乱的关键词列表（最多 count 个）
    """
    log.info("正在从 Bing 首页抓取热搜关键词...")
    keywords = []
    seen = set()

    # ── 第一层：主抓取 ──
    for selector in TRENDING_SELECTORS_LAYER1:
        batch = _extract_keywords_from_elements(page, selector, seen)
        keywords.extend(batch)

    log.info(f"  第一层抓取到 {len(keywords)} 个关键词")

    # ── 第二层：滚动页面触发懒加载，再补抓一轮 ──
    if len(keywords) < count:
        log.info("  关键词不足，滚动页面寻找更多...")
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        except Exception:
            pass

        for selector in TRENDING_SELECTORS_LAYER2:
            batch = _extract_keywords_from_elements(page, selector, seen)
            keywords.extend(batch)

        log.info(f"  第二层补抓后共 {len(keywords)} 个关键词")

    # ── 第三层：数量补齐 — 抓取不足时从内置词库补足差额 ──
    if len(keywords) == 0:
        log.warning("  未能从 Bing 抓取到任何关键词，启用内置词库兜底")
        keywords = list(HOT_KEYWORDS_BACKUP)
    elif len(keywords) < count:
        log.info(f"  从 Bing 获取到 {len(keywords)} 个关键词，从内置词库补充至 {count} 个")
        backup = list(HOT_KEYWORDS_BACKUP)
        random.shuffle(backup)
        for kw in backup:
            if kw not in keywords:
                keywords.append(kw)
                if len(keywords) >= count:
                    break
    else:
        log.info(f"  本次从 Bing 获取到 {len(keywords)} 个最新关键词")

    random.shuffle(keywords)
    return keywords[:count]


# ── 自动搜索加分 ──────────────────────────────────────────
def perform_searches(page: Page, keywords: list[str]) -> int:
    """
    用给定关键词依次执行 Bing 搜索（模拟搜索栏输入，而非 URL 拼接）。
    只在首次导航到 Bing 首页，后续直接操作搜索框，避免重复 goto 的导航竞态。

    Args:
        page: Playwright Page 对象
        keywords: 搜索关键词列表

    Returns:
        成功完成的搜索次数
    """
    log.info(f"开始自动搜索 ({len(keywords)} 个关键词)...")

    # 首次导航到 Bing 首页
    if not safe_goto(page, BING_HOME, timeout=15000):
        log.error("  无法加载 Bing 首页，搜索阶段中止")
        return 0

    success_count = 0
    for i, kw in enumerate(keywords, 1):
        try:
            # 1. 等待搜索框出现
            page.wait_for_selector("#sb_form_q", timeout=10000)

            # 2. 清空搜索框并输入关键词
            search_box = page.locator("#sb_form_q")
            search_box.click()
            search_box.fill(kw)

            # 3. 回车搜索
            page.keyboard.press("Enter")

            # 4. 等待搜索结果页面加载完毕（networkidle 确保所有请求完成）
            page.wait_for_load_state("networkidle")

            # 5. 随机间隔（模拟人类搜索节奏）
            delay = random.uniform(SEARCH_INTERVAL_MIN, SEARCH_INTERVAL_MAX)
            log.info(f"  [{i:2d}/{len(keywords)}] 搜索: {kw}  (等待 {delay:.1f}s)")
            time.sleep(delay)

            success_count += 1
        except Exception as e:
            log.error(f"  [{i:2d}/{len(keywords)}] 搜索失败: {kw} - {e}")
            # 尝试恢复页面状态：回到 Bing 首页
            try:
                safe_goto(page, BING_HOME, timeout=15000, retries=1)
            except Exception:
                pass
            continue

    log.info(f"搜索完成: 成功 {success_count}/{len(keywords)}")
    return success_count


# ── 通用辅助函数 ────────────────────────────────────────────
def safe_goto(page: Page, url: str, timeout: int = 30000, retries: int = 2) -> bool:
    """
    带重试的页面导航。通过 about:blank 中转恢复页面状态，避免
    'interrupted by another navigation' 竞态问题。

    Args:
        page: Playwright Page 对象
        url: 目标 URL
        timeout: 单次导航超时（毫秒）
        retries: 重试次数

    Returns:
        True 如果导航成功，False 如果所有重试都失败
    """
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning(f"  导航失败 (尝试 {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2)
                # about:blank 中转：清空页面导航状态
                try:
                    page.goto("about:blank", wait_until="domcontentloaded", timeout=10000)
                    time.sleep(1)
                except Exception:
                    pass
    return False


def _try_click(page: Page, selectors: list[str], timeout: int = 5000) -> bool:
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


def _safe_click_with_popup(page: Page, element) -> bool:
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


# ── Earn 页面加分项 ─────────────────────────────────────────
# ============================================================
# 选择器策略：基于页面结构定位，不依赖文字/积分数字（每天变）
# - 简单任务：带 search?q= / spotlight/ / wallpaper 的链接
# - Punchcard：/earn/quest/ 入口，进去找 CTA 按钮
# - CTA 特征：a[aria-label][href*="search?q="]:not([aria-disabled])
# ============================================================

# Earn 页面的简单任务链接模式
EARN_SIMPLE_TASK_SELECTORS = [
    "a[href*='search?q=']:not([href*='/quest/'])",
    "a[href*='spotlight/']",
    "a[href*='wallpaper']",
]

# Punchcard 入口
EARN_PUNCHCARD_SELECTOR = "a[href*='/earn/quest/']"

# Punchcard 内的 CTA（子任务按钮）
EARN_CTA_SELECTOR = "a[aria-label][href*='search?q=']:not([aria-disabled='true'])"

# "更多活动"展开（保留兜底）
EARN_MORE_ACTIVITIES_SELECTORS = [
    "text='More activities'",
    "text='更多活动'",
    "[aria-label*='More activities']",
    "[aria-label*='更多活动']",
    "a:has-text('更多活动')",
]


def complete_earn_tasks(page: Page, max_tasks: int = 10) -> int:
    """
    处理 Earn 页面加分项（两阶段）：
    - 阶段 A：简单任务（search/spotlight/wallpaper 链接）→ 直接点击
    - 阶段 B：Punchcard 任务 → 进入 quest 页面，找 CTA 逐个点击

    Args:
        page: Playwright Page 对象（需已登录）
        max_tasks: 最多处理的任务数

    Returns:
        成功完成的任务数量
    """
    log.info("正在处理 Earn 页面加分项...")

    if not safe_goto(page, EARN_URL):
        log.warning("无法加载 Earn 页面")
        return 0

    # 等待页面渲染
    try:
        page.wait_for_selector("a[href*='search?q=']", timeout=25000)
    except Exception:
        log.warning("Earn 页面任务加载超时")
        time.sleep(5)

    time.sleep(3)

    def _collect_simple_tasks() -> list:
        """收集当前页面的简单任务链接（不包含 punchcard）"""
        tasks = []
        seen_hrefs = set()

        for selector in EARN_SIMPLE_TASK_SELECTORS:
            try:
                elements = page.locator(selector).all()
                for el in elements:
                    try:
                        if not el.is_visible():
                            continue
                        href = (el.get_attribute("href") or "").strip()
                        if not href or href in seen_hrefs:
                            continue
                        seen_hrefs.add(href)
                        tasks.append(el)
                    except Exception:
                        continue
            except Exception:
                continue

        return tasks

    tasks_done = 0

    # ═══ 阶段 A：简单任务 ═══
    simple_tasks = _collect_simple_tasks()
    log.info(f"  检测到 {len(simple_tasks)} 个简单任务")

    for el in simple_tasks:
        if tasks_done >= max_tasks:
            break
        try:
            text = el.inner_text().strip().replace("\n", " ")[:40]
            href = (el.get_attribute("href") or "")[:70]
            log.info(f"  点击任务: {text}")
            _safe_click_with_popup(page, el)
            tasks_done += 1
            time.sleep(random.uniform(1.5, 3.0))
        except Exception as e:
            log.error(f"  简单任务失败: {e}")
            continue

    # ═══ 阶段 B：Punchcard（quest）任务 ═══
    if tasks_done < max_tasks:
        punchcard_entries = page.locator(EARN_PUNCHCARD_SELECTOR).all()
        # 去重
        seen_punchcards = set()
        unique_punchcards = []
        for pc in punchcard_entries:
            try:
                if pc.is_visible():
                    h = pc.get_attribute("href") or ""
                    if h and h not in seen_punchcards:
                        seen_punchcards.add(h)
                        unique_punchcards.append((pc, h))
            except Exception:
                continue

        log.info(f"  检测到 {len(unique_punchcards)} 个 punchcard")

        for pc_el, pc_href in unique_punchcards:
            if tasks_done >= max_tasks:
                break
            try:
                pc_text = pc_el.inner_text().strip().replace("\n", " ")[:60]
                log.info(f"  进入 punchcard: {pc_text}")

                # punchcard 链接是同站导航，新开标签页访问
                full_url = f"https://rewards.bing.com{pc_href}" if pc_href.startswith("/") else pc_href
                pc_page = page.context.new_page()
                pc_page.goto(full_url, timeout=30000)
                pc_page.wait_for_load_state("domcontentloaded")
                time.sleep(4)

                # 找所有未禁用的 CTA
                ctas = pc_page.locator(EARN_CTA_SELECTOR).all()
                log.info(f"    punchcard 内有 {len(ctas)} 个可点击 CTA")

                for cta_el in ctas:
                    if tasks_done >= max_tasks:
                        break
                    try:
                        cta_text = cta_el.inner_text().strip() or cta_el.get_attribute("aria-label") or "CTA"
                        log.info(f"      点击 CTA: {cta_text[:40]}")
                        # CTA 链接有 target="_blank"，用 expect_popup 处理弹窗
                        with pc_page.expect_popup(timeout=10000) as popup_info:
                            cta_el.click()
                        new_page = popup_info.value
                        new_page.wait_for_load_state("domcontentloaded")
                        time.sleep(random.randint(5, 8))
                        new_page.close()
                        tasks_done += 1
                        time.sleep(random.uniform(1.0, 2.0))
                    except Exception:
                        continue

                pc_page.close()
                time.sleep(1)

            except Exception as e:
                log.error(f"  punchcard 处理异常: {e}")
                continue

    # ── 第二轮：尝试展开"更多活动"再收集 ──
    more_clicked = _try_click(page, EARN_MORE_ACTIVITIES_SELECTORS, timeout=5000)
    if more_clicked:
        log.info("  已展开'更多活动'区域")
        time.sleep(3)

        more_tasks = _collect_simple_tasks()
        log.info(f"  第二轮检测到 {len(more_tasks)} 个简单任务")

        for el in more_tasks:
            if tasks_done >= max_tasks:
                break
            try:
                text = el.inner_text().strip().replace("\n", " ")[:40]
                log.info(f"  点击任务: {text}")
                _safe_click_with_popup(page, el)
                tasks_done += 1
                time.sleep(random.uniform(1.5, 3.0))
            except Exception as e:
                log.error(f"  任务失败: {e}")
                continue
    else:
        log.info("  未找到'更多活动'按钮，无需展开")

    log.info(f"Earn 任务完成: {tasks_done} 个")
    return tasks_done


# ── Dashboard 可领取积分 ─────────────────────────────────────
# ============================================================
# 新版 Dashboard 使用卡片式布局，"可领取"是一张卡片
# 结构："可领取" (p.text-labelControl) → 数量 (p.text-pageHeader) → "领取" (p.text-metadata)
# 点击卡片触发领取（无弹窗/侧边栏）
# ============================================================

# "可领取" 卡片内的数量元素
REDEEMABLE_AMOUNT_SELECTOR = "p.text-pageHeader"

# "可领取"文本标签（用于定位卡片）
REDEEMABLE_LABEL_SELECTOR = "p.text-labelControl:has-text('可领取')"

# 2026-10 改版：点击"可领取"卡片会弹出"领取积分"确认弹窗（内含待领取明细），
# 必须再点弹窗里的"领取积分"按钮才真正到账；旧版点击卡片即直接领取已失效
CLAIM_DIALOG_SELECTOR = "[role='dialog'], [data-state='open']"
CLAIM_CONFIRM_SELECTOR = "button:has-text('领取积分')"


def _read_card_amount(page: Page) -> "int | None":
    """按脚本同款定位链读"可领取"数量；卡片不存在返回 None"""
    label = page.locator(REDEEMABLE_LABEL_SELECTOR).first
    if not label.is_visible():
        return None
    card = label
    for _ in range(6):
        try:
            card = card.locator("xpath=..")
            cls = card.get_attribute("class") or ""
            if "hover" in cls and ("card" in cls.lower() or "cursor-pointer" in cls):
                break
        except Exception:
            break
    amount_el = card.locator(REDEEMABLE_AMOUNT_SELECTOR).first
    text = amount_el.inner_text().strip() if amount_el.is_visible() else "0"
    digits = text.replace(",", "").strip()
    return int(digits) if digits.isdigit() else 0


def collect_redeemable_points(page: Page) -> bool:
    """
    在 Dashboard 的"可领取"卡片上领取积分。
    新版 Dashboard 使用卡片式布局，点击卡片后弹出"领取积分"确认弹窗，
    需再点弹窗内的"领取积分"按钮；成功判定以卡片消失/数量归零为准。

    Args:
        page: Playwright Page 对象（需已登录且在 Dashboard 或附近页面）

    Returns:
        True 如果成功领取积分，False 如果跳过或失败
    """
    log.info("正在尝试领取积分...")

    # 确保在 Dashboard 页面
    if not safe_goto(page, DASHBOARD_URL):
        log.warning("无法加载 Dashboard")
        return False

    time.sleep(4)

    # 步骤 1: 找"可领取"卡片，读取可领取数量
    try:
        amount = _read_card_amount(page)
        if amount is None:
            log.warning("  未找到'可领取'卡片")
            return False
        if amount == 0:
            log.info("  无可领取积分 (0)，跳过")
            return False

        # 步骤 2: 点击卡片（兼容千位分隔符，如 "1,250"）
        log.info(f"  可领取积分: {amount}，点击卡片领取...")
        label_el = page.locator(REDEEMABLE_LABEL_SELECTOR).first
        card = label_el
        for _ in range(6):
            try:
                card = card.locator("xpath=..")
                cls = card.get_attribute("class") or ""
                if "hover" in cls and ("card" in cls.lower() or "cursor-pointer" in cls):
                    break
            except Exception:
                break
        card.click()

        # 步骤 3: 确认弹窗；弹窗容器先出现、按钮后渲染，用 wait_for 等按钮可见
        try:
            confirm = page.locator(CLAIM_CONFIRM_SELECTOR).first
            confirm.wait_for(state="visible", timeout=6000)
            log.info("  检测到'领取积分'确认弹窗，点击确认按钮...")
            confirm.click()
        except Exception:
            log.info("  未出现确认弹窗（可能点击即领取）")

        time.sleep(3)

        # 步骤 4: 校验，卡片消失或数量归零才算成功；仍 >0 则刷新一次再核对
        left = _read_card_amount(page)
        if left is not None and left > 0:
            time.sleep(2)
            safe_goto(page, DASHBOARD_URL)
            time.sleep(4)
            left = _read_card_amount(page)
        if left is None or left == 0:
            log.info("  ✓ 积分领取完成")
            return True
        log.warning(f"  点击后仍剩 {left} 分未到账，视为失败")
        return False

    except Exception as e:
        log.warning(f"  领取积分异常: {e}")
        return False


# ── Daily Set 每日活动任务 ─────────────────────────────────
def complete_daily_set(page: Page) -> int:
    """
    完成 Rewards 控制面板的 Daily Set 任务。

    Args:
        page: Playwright Page 对象

    Returns:
        成功完成的任务数量
    """
    log.info("正在完成 Daily Set 每日活动...")

    # 导航到 Rewards 控制面板
    if not safe_goto(page, DASHBOARD_URL):
        log.warning("无法加载 Dashboard 页面，跳过 Daily Set")
        return 0

    # 等待任务卡片加载
    try:
        page.wait_for_selector(
            "#dailyset",
            timeout=25000
        )
    except Exception:
        log.warning("等待任务卡片超时——可能需要手动登录")
        # 给一点时间让用户登录
        time.sleep(5)
        log.info(f"当前页面: {page.title()}")

    time.sleep(2)

    # 定位每日任务卡片
    daily_tasks = page.locator(
        "#dailyset a[href*='search?q=']"
    ).all()

    # 去重
    unique_tasks = []
    seen_hrefs = set()
    for task in daily_tasks:
        try:
            if task.is_visible():
                href = task.get_attribute("href") or ""
                if href and href not in seen_hrefs:
                    seen_hrefs.add(href)
                    unique_tasks.append(task)
        except Exception:
            continue

    log.info(f"检测到 {len(unique_tasks)} 个 Daily Set 任务卡片")

    if len(unique_tasks) == 0:
        log.warning("未找到 Daily Set 任务卡片（可能今日任务已全部完成）")
        return 0

    tasks_done = 0
    for index, task in enumerate(unique_tasks):
        try:
            task_text = task.inner_text().strip().replace("\n", " ")
            task_text = task_text[:40] + ".." if len(task_text) > 40 else task_text
            log.info(f"  [任务 {index+1}] {task_text}")

            # 模拟人类延迟
            delay = random.uniform(1.5, 3.0)
            time.sleep(delay)

            # 点击卡片，弹出新标签页
            with page.expect_popup() as popup_info:
                task.click()

            new_page = popup_info.value
            new_page.wait_for_load_state("domcontentloaded")
            log.info(f"    新标签页: {new_page.title()}")

            # 停留以记录积分
            stay_time = random.randint(5, 8)
            time.sleep(stay_time)

            # 关闭新标签页
            new_page.close()
            log.info(f"    任务 {index+1} 完成 ✓")
            tasks_done += 1

        except Exception as e:
            log.error(f"    任务 {index+1} 失败: {e}")
            continue

    log.info(f"Daily Set 完成: {tasks_done}/{len(unique_tasks)}")
    return tasks_done


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="微软 Rewards 每日签到自动化")
    parser.add_argument(
        "--exit-when-done",
        action="store_true",
        help="签到完成后自动关闭浏览器退出（适合计划任务/无人值守运行）",
    )
    return parser.parse_args()


# ── 主流程 ─────────────────────────────────────────────────
def main():
    args = parse_args()
    log.info("=" * 60)
    log.info("微软 Rewards 每日签到脚本 启动")
    log.info(f"日期: {datetime.now().strftime('%Y-%m-%d')}")
    log.info(f"Profile: {PROFILE_DIR}")
    log.info("=" * 60)

    with sync_playwright() as p:
        context = None
        try:
            # 依次尝试浏览器通道（msedge → chrome → Playwright 内置 Chromium）
            context = None
            last_error = None
            for channel in BROWSER_CHANNELS:
                try:
                    label = channel if channel is not None else "built-in Chromium"
                    log.info(f"正在尝试启动浏览器 ({label})...")
                    kwargs = dict(
                        user_data_dir=PROFILE_DIR,
                        headless=False,
                        no_viewport=True,
                        args=["--start-maximized"],
                    )
                    if channel is not None:
                        kwargs["channel"] = channel
                    context = p.chromium.launch_persistent_context(**kwargs)
                    log.info(f"  浏览器启动成功 ({label})")
                    break
                except Exception as e:
                    log.warning(f"  浏览器通道 '{channel}' 不可用: {e}")
                    last_error = e
                    continue

            if context is None:
                raise RuntimeError(
                    f"所有浏览器通道均无法启动。请安装 Edge/Chrome，"
                    f"或运行 playwright install chromium 后重试。"
                    f"末次错误: {last_error}"
                )
            page: Page = context.pages[0] if context.pages else context.new_page()

            # ── 阶段 1: 加载 Bing 首页，获取热搜关键词 ──
            log.info("正在加载 Bing 首页...")
            safe_goto(page, BING_HOME)
            time.sleep(2)

            keywords = fetch_trending_keywords(page, count=SEARCH_COUNT)
            log.info(f"今日关键词 ({len(keywords)}): {', '.join(keywords[:5])}...")

            # ── 阶段 2: 自动搜索加分 ──
            search_ok = perform_searches(page, keywords)

            # ── 阶段 3: Earn 页面加分项 ──
            earn_ok = complete_earn_tasks(page)

            # ── 阶段 4: Daily Set 每日活动 ──
            daily_ok = complete_daily_set(page)

            # ── 阶段 5: 领取积分 ──
            redeemed = collect_redeemable_points(page)

            # ── 汇总 ──
            log.info("=" * 60)
            log.info("签到完成! 汇总:")
            log.info(f"  搜索: {search_ok}/{SEARCH_COUNT} 次")
            log.info(f"  Earn 任务: {earn_ok} 个")
            log.info(f"  Daily Set: {daily_ok} 个任务")
            log.info(f"  领取积分: {'成功' if redeemed else '跳过/未找到'}")
            log.info(f"  日志文件: {LOG_FILE}")
            if args.exit_when_done:
                log.info("已启用 --exit-when-done，签到完成，自动退出。")
                return
            log.info("浏览器保持开启，你可以查验积分。按 Ctrl+C 退出。")
            log.info("=" * 60)

            # 保持开启
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("\n用户中断，正在关闭浏览器...")
        except Exception as e:
            log.error(f"运行异常: {e}", exc_info=True)
            if args.exit_when_done:
                raise
        finally:
            if context is not None:
                context.close()
                log.info("浏览器已关闭。")


if __name__ == "__main__":
    main()
