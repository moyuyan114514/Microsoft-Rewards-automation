"""
rewards_bot.py —— 微软 Rewards 每日签到 v2（融合重写版）

融合三家开源项目的长处（详细致谢与出处见 README）：
  Microsoft-Rewards-Script（TheNetsky / chiihero 中文本地化）：
      - 积分目标驱动搜索：每搜几次核对积分增量，积分停涨即提前收手，
        而不是死板搜满固定次数
      - "不完美"拟人策略：随机不刷满搜索目标（真人有状态波动），
        静默时段、当天完成不重跑、启动时刻随机化
  safarsin/AutoRewarder：
      - 贝塞尔鼠标轨迹 / 逐键拟人输入 / 拟人滚动（实现在 humanize.py）
  本项目旧版 daily_checkin.py：
      - Bing 热搜抓取、Daily Set / Earn / Punchcard / 积分领取的选择器体系

用法：
  python rewards_bot.py                     # 跑完保持浏览器开启（默认）
  python rewards_bot.py --exit-when-done    # 跑完自动退出，适合计划任务
  python rewards_bot.py --config my.json    # 指定配置文件（默认 config.json）
"""

import argparse
import json
import logging
import random
import re
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import browser as browser_layer
from humanize import Human

# ── 编码兼容 ──────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="ignore")

# ── 常量 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent

BING_HOME = "https://cn.bing.com"
DASHBOARD_URL = "https://rewards.bing.com/dashboard"
EARN_URL = "https://rewards.bing.com/earn"

SEARCH_BOX = "#sb_form_q"
RESULT_LINK = "#b_results .b_algo h2"

# 积分展示元素：Dashboard 上多处复用（用户名/总积分/可领取），总积分是其中最大的纯数字
BALANCE_SELECTOR = "p.text-pageHeader"

PROFILE_DIR = SCRIPT_DIR / "edge_profile"
LOG_DIR = SCRIPT_DIR / "logs"
LOG_FILE = LOG_DIR / "rewards_bot.log"
STATE_FILE = LOG_DIR / "last-success.txt"  # 记录最后成功日期，供"当天不重跑"判断

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # 对应 Python weekday() 0-6

# ── 默认配置（config.json 可覆盖任意子集） ─────────────────
DEFAULT_CONFIG = {
    "humanize": {
        "enabled": True,
        "quietHours": [],                   # 例: [{"days": ["mon","tue","wed","thu","fri","sat","sun"], "start": "02:30", "end": "07:30"}]
        "skipWhenCompletedToday": False,    # 挂计划任务时建议开
        "startJitterSec": [0, 0],           # 启动随机延迟区间，避免每天准点跑
        "searchTargetRatio": [0.85, 1.0],   # 每天随机完成目标的比例——故意不刷满
        "typingDelayMs": [40, 110],
        "missProb": 0.05,
    },
    "search": {
        "desktopCount": 30,
        "intervalSec": [8, 20],
        "searchRefreshEvery": 8,            # 每搜 N 次回一次 Bing 首页
        "randomScrollProb": 0.6,
        "randomClickProb": 0.3,
        "resultVisitSec": [4, 10],
        "stagnantBatches": 2,               # 连续 N 次核对积分无增长 → 提前结束
        "pointsCheckEvery": 5,              # 每搜 N 次核对一次积分
    },
    "tasks": {
        "dailySet": True,
        "earn": True,
        "punchcard": True,
        "redeem": True,
        "maxTasks": 10,
    },
    "mobile": {
        "enabled": False,                   # 移动端搜索：需单独登录一次 edge_profile_mobile
        "count": 20,
        "profileDir": "edge_profile_mobile",
    },
    "runtime": {
        "loginTimeoutMin": 10,
        "exitWhenDone": False,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 里的值覆盖 base，缺的用 base 的"""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return deep_merge(DEFAULT_CONFIG, json.load(f))
    return dict(DEFAULT_CONFIG)


# ── 日志 ──────────────────────────────────────────────────
log = logging.getLogger("rewards_bot")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("rewards_bot")
    logger.setLevel(logging.DEBUG)

    fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ── 热搜关键词（沿用旧版多选择器抓取 + 内置词库兜底） ──────
HOT_KEYWORDS_BACKUP = [
    "人工智能最新进展", "ChatGPT 更新", "苹果新品发布", "iPhone 最新消息",
    "华为 Mate 系列", "特斯拉新车型", "量子计算突破", "5G 应用场景",
    "元宇宙发展", "区块链技术",
    "股市行情", "比特币价格", "美联储利率", "人民币汇率",
    "房价走势", "新能源车补贴",
    "世界杯", "NBA 季后赛", "英超联赛", "欧冠决赛",
    "奥运会", "F1 赛事",
    "热门电影推荐", "豆瓣高分", "综艺节目", "热门歌曲",
    "明星动态", "演唱会",
    "天气预报", "旅游景点推荐", "美食做法", "减肥方法",
    "健康养生", "家居装修",
    "高考", "考研", "留学申请", "编程学习",
    "英语学习", "在线课程",
    "今日新闻", "国际形势", "环保政策", "交通出行",
    "疫情防控", "教育改革",
    "冷知识", "奇闻趣事", "历史故事", "科幻小说",
    "宇宙探索", "海洋生物",
]

SKIP_PATTERNS = [
    "热点", "翻译", "顺流", "必应", "Bing", "bing",
    "奥基乔比", "苏必利尔", "庞恰特雷恩",
]

TRENDING_SELECTORS = [
    "#trending a[href*='search']",
    "#sc_hdu a[href*='search']",
    ".hp_sw_trend a",
    "#hp_sw_trend a",
    ".vs_sw_trend a",
    "a[href*='search?q=']",
    ".hp_tile a[href*='search']",
    ".cardNews a[href*='search']",
    ".content a[href*='search']",
    "a[href*='q=']",
    "[data-trending] a",
    ".ntc_cl_c a",
]


def _extract_keywords(page, selector: str, seen: set) -> list:
    result = []
    try:
        for el in page.locator(selector).all():
            try:
                if not el.is_visible():
                    continue
                text = el.inner_text().strip()
                if not text or len(text) < 2:
                    continue
                cleaned = re.sub(r"^[0-9A-Z]\s*", "", text)  # 去掉排名数字前缀
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


def collect_query_pool(page, need: int) -> list:
    """从 Bing 首页抓热搜，不足则滚动补抓，仍不足用内置词库补齐，最后打乱"""
    log.info("正在抓取热搜关键词...")
    keywords, seen = [], set()
    for selector in TRENDING_SELECTORS:
        keywords.extend(_extract_keywords(page, selector, seen))
        if len(keywords) >= need * 2:
            break

    if len(keywords) < need:
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
        except Exception:
            pass
        for selector in TRENDING_SELECTORS:
            keywords.extend(_extract_keywords(page, selector, seen))
            if len(keywords) >= need * 2:
                break

    if not keywords:
        log.warning("  未能抓取热搜，使用内置词库")
        keywords = list(HOT_KEYWORDS_BACKUP)
    elif len(keywords) < need:
        backup = [kw for kw in HOT_KEYWORDS_BACKUP if kw not in seen]
        random.shuffle(backup)
        keywords.extend(backup[: need - len(keywords)])

    random.shuffle(keywords)
    log.info(f"  查询词池: {len(keywords)} 个")
    return keywords


def make_query_iter(pool: list):
    """把词池变成无限迭代器（耗尽后重洗循环），避免长会话中途断粮"""
    pool = list(pool) or list(HOT_KEYWORDS_BACKUP)
    random.shuffle(pool)
    while True:
        if not pool:
            pool = list(HOT_KEYWORDS_BACKUP)
            random.shuffle(pool)
        yield pool.pop()


# ── 通用导航 / 积分 ───────────────────────────────────────
def safe_goto(page, url: str, timeout: int = 30000, retries: int = 3) -> bool:
    """带重试导航，about:blank 中转避免导航竞态（沿用旧版方案）。
    rewards.bing.com 在国内网络下时快时慢，重试间隔逐步拉长。"""
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning(f"  导航失败 (尝试 {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(min(6.0, 2.0 * attempt))
                try:
                    page.goto("about:blank", wait_until="domcontentloaded", timeout=10000)
                    time.sleep(1)
                except Exception:
                    pass
    return False


def read_points(context, page=None) -> "int | None":
    """读当前积分。读不到返回 None，调用方需容忍（此时走固定次数不提前收手）。

    老接口 getuserinfo?type=1 已失效（2026-10-03 探测：纯请求被重定向到
    OIDC 登录握手页，带 header 返回 401，页面内同源 fetch 接口不存在），
    改从 Dashboard DOM 读取：p.text-pageHeader 有多处（用户名/总积分/可领取），
    总积分是其中最大的纯数字（兼容 "10,040" 千位分隔符）。

    page 已在 rewards 域时直接读当前页；否则开临时标签页加载 Dashboard，
    不打断主页面正在进行的搜索。
    """
    tmp = None
    try:
        if page is not None and "rewards.bing.com" in (page.url or ""):
            target = page
        else:
            tmp = context.new_page()
            tmp.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=20000)
            tmp.wait_for_selector(BALANCE_SELECTOR, timeout=15000)
            target = tmp
        texts = target.locator(BALANCE_SELECTOR).all_inner_texts()
        nums = []
        for t in texts:
            digits = t.replace(",", "").strip()
            if digits.isdigit():
                nums.append(int(digits))
        return max(nums) if nums else None
    except Exception:
        return None
    finally:
        if tmp is not None:
            try:
                tmp.close()
            except Exception:
                pass


# ── 登录检测 ──────────────────────────────────────────────
LOGIN_INDICATORS = [
    "#dailyset", "#more-activities", "#opportunities",
    "a[href*='/earn/']", "p.text-labelControl",
]


def looks_logged_in(page) -> bool:
    if "login.live.com" in page.url:
        return False
    for sel in LOGIN_INDICATORS:
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            pass
    return False


def ensure_login(page, timeout_min: int) -> bool:
    """确认登录态；未登录则引导用户在窗口里手动登录。

    等待期间【只观察不打扰】：不会反复导航刷新页面（那会让用户根本
    无法输入账号密码），只被动轮询 page.url；仅当用户离开登录页
    （URL 发生变化且不再是 login.live.com）时才做一次登录态验证。
    """
    if not safe_goto(page, DASHBOARD_URL):
        return False
    if looks_logged_in(page):
        return True

    # 重新导航一次到 Dashboard（会重定向到 login.live.com 登录页，登录后自动跳回）
    safe_goto(page, DASHBOARD_URL, retries=2)
    log.info(f"未登录——请在浏览器窗口中登录微软账号（最长等待 {timeout_min} 分钟）")
    log.info("  脚本不会刷新页面干扰你，登录完成后自动继续")

    deadline = time.time() + timeout_min * 60
    last_url = page.url
    while time.time() < deadline:
        time.sleep(5)
        try:
            url = page.url
        except Exception:
            continue  # 页面正在跳转中
        if "login.live.com" in url:
            last_url = url
            continue  # 用户还在登录流程里，安静等待
        if url == last_url:
            continue  # 页面无变化，不重复验证
        last_url = url

        # 用户离开了登录页 → 验证一次登录态
        if safe_goto(page, DASHBOARD_URL, retries=1) and looks_logged_in(page):
            log.info("  登录成功 ✓")
            time.sleep(3)
            return True
        log.info("  未检测到登录态，继续等待（请确认已完成登录 rewards.bing.com）")

    # 指标选择器可能因改版全部失效；只要没停在登录页就带警告继续
    if "login.live.com" not in page.url:
        log.warning("  等待超时，但未跳转登录页，继续执行（若任务全部失败请检查登录态）")
        return True
    log.error("  等待登录超时")
    return False


# ── 搜索 ──────────────────────────────────────────────────
def do_one_search(page, human: Human, query: str, cfg_search: dict):
    """单次搜索：点击搜索框 → 全选覆盖 → 逐键输入 → 回车 → 拟人化闲逛"""
    page.wait_for_selector(SEARCH_BOX, timeout=15000)
    box = page.locator(SEARCH_BOX)

    human.click(box)                # 真实轨迹移动 + 按下抬起
    human.press("Control+A")        # 全选旧词，直接输入覆盖（对真人习惯的近似）
    human.type_text(query)
    human.pause(0.3, 0.8)
    human.press("Enter")

    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    human.pause(2, 4)

    if random.random() < cfg_search["randomScrollProb"]:
        human.scroll_page(dwell=(1.5, 4.0))

    if random.random() < cfg_search["randomClickProb"]:
        _click_random_result(page, human, cfg_search)


def _click_random_result(page, human: Human, cfg_search: dict):
    """按概率点开一条搜索结果停留，看完回来 —— 真人不会搜完就走"""
    try:
        links = page.locator(RESULT_LINK)
        n = min(links.count(), 8)
        if n == 0:
            return
        before = set(page.context.pages)
        if not human.click(links.nth(random.randint(0, n - 1))):
            return

        human.pause(*cfg_search["resultVisitSec"])

        new_pages = [p for p in page.context.pages if p not in before]
        for p in new_pages:
            p.close()
        if not new_pages:
            try:
                page.go_back(timeout=10000)
            except Exception:
                pass
        human.pause(1, 2)
    except Exception as e:
        log.debug(f"  随机点击结果异常（忽略）: {e}")


def run_search_session(context, page, human: Human, query_iter, count: int,
                       cfg: dict, tag: str) -> int:
    """积分目标驱动的搜索会话：
    - 目标次数 = count × 随机比例（humanize.searchTargetRatio，故意不刷满）
    - 每 pointsCheckEvery 次核对积分，连续 stagnantBatches 次零增长即提前结束
    """
    cfg_search = cfg["search"]
    humanize = cfg["humanize"]

    target = count
    if humanize["enabled"] and humanize.get("searchTargetRatio"):
        lo, hi = humanize["searchTargetRatio"]
        ratio = random.uniform(lo, hi)
        target = max(1, round(count * ratio))
        if target < count:
            log.info(f"  拟人化：本次目标随机打折 {count}→{target} (ratio={ratio:.2f})")

    prev_points = read_points(context, page)
    log.info(f"[{tag}] 开始搜索，目标 {target} 次" + (f"，当前积分 {prev_points}" if prev_points is not None else "（积分读取不可用）"))

    done, stagnant = 0, 0
    for i in range(1, target + 1):
        if i % cfg_search["searchRefreshEvery"] == 0:
            safe_goto(page, BING_HOME, timeout=15000, retries=1)
        try:
            query = next(query_iter)
            do_one_search(page, human, query, cfg_search)
            done += 1
            delay = random.uniform(*cfg_search["intervalSec"])
            if random.random() < 0.05:  # 偶发走神，拖长间隔
                delay += random.uniform(20, 60)
            log.info(f"  [{tag} {i:2d}/{target}] {query}（歇 {delay:.0f}s）")
            time.sleep(delay)
        except Exception as e:
            log.error(f"  [{tag} {i:2d}/{target}] 搜索失败: {e}")
            safe_goto(page, BING_HOME, timeout=15000, retries=1)
            continue

        if i % cfg_search["pointsCheckEvery"] == 0:
            cur = read_points(context, page)
            if cur is not None and prev_points is not None:
                gained = cur - prev_points
                if gained > 0:
                    stagnant = 0
                    log.info(f"  [{tag}] 积分 +{gained} → {cur}")
                else:
                    stagnant += 1
                    log.info(f"  [{tag}] 积分无增长 ({stagnant}/{cfg_search['stagnantBatches']})")
                    if stagnant >= cfg_search["stagnantBatches"]:
                        log.info(f"  [{tag}] 积分已停涨，提前收手（已完成 {done} 次）")
                        break
            if cur is not None:
                prev_points = cur

    log.info(f"[{tag}] 搜索结束，完成 {done}/{target}")
    return done


# ── Daily Set / Earn / Punchcard / 领积分 ─────────────────
def _abs_url(href: str, base: str = "https://rewards.bing.com") -> str:
    """任务卡片里的 href 可能是绝对/相对/协议相对三种形态，统一成可访问 URL"""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        # rewards 页里的 /search?q= 链接属于 Bing 域，其余（/earn/...）留在本域
        return f"https://www.bing.com{href}" if href.startswith("/search") else base + href
    return href


def _snapshot_hrefs(page, selector: str, timeout: int = 3000) -> list:
    """把定位器命中的链接固化成 href 字符串列表。

    Rewards 页面在任务完成后会局部重渲染，.all() 返回的定位器到后面再解析
    会等满 30s 超时并打断整个任务循环（2026-10-01 punchcard 事故）。
    所以一律先取 href 快照、再按 URL 逐条访问；单条失效只丢自己，
    timeout 调短保证不会长时间挂住。
    """
    hrefs, seen = [], set()
    try:
        for el in page.locator(selector).all():
            try:
                if not el.is_visible():
                    continue
                href = (el.get_attribute("href", timeout=timeout) or "").strip()
                if href and href not in seen:
                    seen.add(href)
                    hrefs.append(href)
            except Exception:
                continue
    except Exception:
        pass
    return hrefs


def _visit_dwell_close(context, url: str, dwell=(5, 9)) -> bool:
    """新开标签页访问 url，停留随机时长后关闭。

    任务卡片/CTA 都是 target=_blank 链接，点击弹出的就是 href 本身，
    直接访问与点击等价，但不吃页面重渲染和点击落点的亏；
    停留时长保留随机性（拟人）。
    """
    tp = None
    try:
        tp = context.new_page()
        tp.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(random.randint(dwell[0], dwell[1]))
        return True
    except Exception as e:
        log.debug(f"  访问任务页失败: {e}")
        return False
    finally:
        if tp is not None:
            try:
                tp.close()
            except Exception:
                pass
            time.sleep(random.uniform(0.8, 1.5))


def complete_daily_set(page, human: Human) -> int:
    log.info("正在完成 Daily Set 每日活动...")
    if not safe_goto(page, DASHBOARD_URL):
        return 0
    try:
        page.wait_for_selector("#dailyset", timeout=25000)
    except Exception:
        log.warning("  等待任务卡片超时")
        time.sleep(5)
    time.sleep(2)

    hrefs = _snapshot_hrefs(page, "#dailyset a[href*='search?q=']")
    log.info(f"  检测到 {len(hrefs)} 个 Daily Set 任务")
    done = 0
    for index, href in enumerate(hrefs, 1):
        human.pause(1.5, 3.0)
        url = _abs_url(href)
        if _visit_dwell_close(page.context, url):
            log.info(f"  任务 {index} ✓")
            done += 1
        else:
            log.error(f"  任务 {index} 失败: {url[:70]}")
    log.info(f"Daily Set 完成: {done}/{len(hrefs)}")
    return done


EARN_SIMPLE_TASK_SELECTORS = [
    "a[href*='search?q=']:not([href*='/quest/'])",
    "a[href*='spotlight/']",
    "a[href*='wallpaper']",
]
EARN_PUNCHCARD_SELECTOR = "a[href*='/earn/quest/']"
EARN_CTA_SELECTOR = "a[aria-label][href*='search?q=']:not([aria-disabled='true'])"


def complete_earn_tasks(page, human: Human, max_tasks: int = 10) -> int:
    """Earn 页面：简单任务直接访问；punchcard 进 quest 子页面逐条访问 CTA。
    全程 href 快照驱动，只有真正访问成功才计数——杜绝"没点上也算完成"。"""
    log.info("正在处理 Earn 页面加分项...")
    if not safe_goto(page, EARN_URL):
        return 0
    try:
        page.wait_for_selector("a[href*='search?q=']", timeout=25000)
    except Exception:
        log.warning("  Earn 页面任务加载超时")
        time.sleep(5)
    time.sleep(3)

    done = 0

    def _do_simple(hrefs: list, seen: set) -> None:
        nonlocal done
        for href in hrefs:
            if done >= max_tasks:
                break
            if href in seen:
                continue
            seen.add(href)
            url = _abs_url(href)
            label = url.split("q=")[-1][:40] if "q=" in url else url[:40]
            log.info(f"  点击任务: {label}")
            if _visit_dwell_close(page.context, url):
                done += 1
                human.pause(1.5, 3.0)
            else:
                log.error(f"  任务失败: {label}")

    # ── 阶段 A：简单任务 ──
    simple_hrefs, seen_hrefs = [], set()
    for selector in EARN_SIMPLE_TASK_SELECTORS:
        for href in _snapshot_hrefs(page, selector):
            if href not in seen_hrefs:
                seen_hrefs.add(href)
                simple_hrefs.append(href)
    log.info(f"  检测到 {len(simple_hrefs)} 个简单任务")
    _do_simple(simple_hrefs, seen_hrefs)

    # ── 阶段 B：punchcard（quest）──
    if done < max_tasks:
        for href in _snapshot_hrefs(page, EARN_PUNCHCARD_SELECTOR):
            if done >= max_tasks:
                break
            log.info(f"  进入 punchcard: {_abs_url(href)[:60]}")
            pc_page = None
            try:
                pc_page = page.context.new_page()
                pc_page.goto(_abs_url(href), timeout=30000, wait_until="domcontentloaded")
                time.sleep(4)
                for cta in _snapshot_hrefs(pc_page, EARN_CTA_SELECTOR):
                    if done >= max_tasks:
                        break
                    if _visit_dwell_close(page.context, _abs_url(cta)):
                        done += 1
                        human.pause(1.0, 2.0)
            except Exception as e:
                log.error(f"  punchcard 处理异常: {e}")
            finally:
                if pc_page is not None:
                    try:
                        pc_page.close()
                    except Exception:
                        pass
                time.sleep(1)

    log.info(f"Earn 任务完成: {done} 个")
    return done


REDEEMABLE_LABEL_SELECTOR = "p.text-labelControl:has-text('可领取')"
REDEEMABLE_AMOUNT_SELECTOR = "p.text-pageHeader"
# 2026-10 改版：点击"可领取"卡片会弹出"领取积分"确认弹窗（内含待领取明细），
# 必须再点弹窗里的"领取积分"按钮才真正到账；旧版点击卡片即直接领取已失效
CLAIM_DIALOG_SELECTOR = "[role='dialog'], [data-state='open']"
CLAIM_CONFIRM_SELECTOR = "button:has-text('领取积分')"


def _read_card_amount(page) -> "int | None":
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


def collect_redeemable_points(page, human: Human) -> bool:
    """领取 Dashboard"可领取"卡片积分（已修复千位分隔符识别问题、确认弹窗流程）。

    成功判定以领取后卡片消失/数量归零为准，不再默认点击即成功。
    """
    log.info("正在尝试领取积分...")
    if not safe_goto(page, DASHBOARD_URL):
        return False
    time.sleep(4)
    try:
        amount = _read_card_amount(page)
        if amount is None:
            log.info("  未找到'可领取'卡片，跳过")
            return False
        if amount == 0:
            log.info("  无可领取积分 (0)，跳过")
            return False

        log.info(f"  可领取 {amount} 分，点击卡片...")
        label = page.locator(REDEEMABLE_LABEL_SELECTOR).first
        card = label
        for _ in range(6):
            try:
                card = card.locator("xpath=..")
                cls = card.get_attribute("class") or ""
                if "hover" in cls and ("card" in cls.lower() or "cursor-pointer" in cls):
                    break
            except Exception:
                break
        human.click(card)

        # 等确认弹窗；未出现（点击即领取的旧版行为）则继续走校验
        try:
            dlg = page.locator(CLAIM_DIALOG_SELECTOR).first
            dlg.wait_for(state="visible", timeout=4000)
            confirm = dlg.locator(CLAIM_CONFIRM_SELECTOR).first
            if confirm.is_visible():
                log.info("  检测到'领取积分'确认弹窗，点击确认按钮...")
                human.click(confirm)
            else:
                log.warning("  弹窗已打开但未找到'领取积分'按钮")
        except Exception:
            log.info("  未出现确认弹窗（可能点击即领取）")

        time.sleep(3)

        # 校验：卡片消失或数量归零才算成功；仍 >0 则刷新一次再核对
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


# ── humanize 门禁 ─────────────────────────────────────────
def _parse_hhmm(value) -> "int | None":
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
    if not m:
        return None
    h, minute = int(m.group(1)), int(m.group(2))
    if h > 23 or minute > 59:
        return None
    return h * 60 + minute


def quiet_wait_minutes(rules) -> float:
    """当前若处于静默时段，返回距离时段结束的分钟数；否则 0"""
    now = datetime.now()
    now_min = now.hour * 60 + now.minute + now.second / 60
    today_key = DAY_KEYS[now.weekday()]

    best = float("inf")
    for rule in rules or []:
        days = [str(d).strip().lower() for d in rule.get("days", [])] or [today_key]
        if today_key not in days:
            continue
        start, end = _parse_hhmm(rule.get("start")), _parse_hhmm(rule.get("end"))
        if start is None or end is None or start == end:
            continue
        if start < end:
            in_range, wait = start <= now_min < end, end - now_min
        else:  # 跨午夜
            if now_min >= start:
                in_range, wait = True, 1440 - now_min + end
            else:
                in_range, wait = now_min < end, end - now_min
        if in_range and wait > 0:
            best = min(best, wait)
    return best if best != float("inf") else 0.0


def _today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def done_today() -> bool:
    try:
        return STATE_FILE.read_text(encoding="utf-8").strip() == _today_key()
    except Exception:
        return False


def mark_done():
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(_today_key(), encoding="utf-8")
    except Exception:
        pass


# ── 主流程 ────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="微软 Rewards 每日签到 v2（融合版）")
    parser.add_argument("--exit-when-done", action="store_true", help="完成后自动退出（计划任务）")
    parser.add_argument("--config", default=str(SCRIPT_DIR / "config.json"), help="配置文件路径")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging()

    cfg = load_config(Path(args.config))
    if args.exit_when_done:
        cfg["runtime"]["exitWhenDone"] = True
    exit_when_done = cfg["runtime"]["exitWhenDone"]
    humanize = cfg["humanize"]

    log.info("=" * 60)
    log.info("微软 Rewards 每日签到 v2 启动")
    log.info(f"日期: {_today_key()}  配置: {args.config}")

    # ── humanize 门禁：静默时段 / 当天已跑 / 启动抖动 ──
    if humanize["enabled"]:
        wait_min = quiet_wait_minutes(humanize.get("quietHours"))
        if wait_min > 0:
            resume = datetime.fromtimestamp(time.time() + wait_min * 60)
            log.info(f"当前处于静默时段，挂起到 {resume:%H:%M} ...")
            time.sleep(wait_min * 60)

        if humanize.get("skipWhenCompletedToday") and done_today():
            log.info("今天已成功完成过，跳过（skipWhenCompletedToday）")
            return

        lo, hi = humanize.get("startJitterSec", [0, 0])
        if hi > 0:
            jitter = random.uniform(lo, hi)
            log.info(f"启动抖动: 等待 {jitter:.0f}s")
            time.sleep(jitter)

    context = None
    pw = None
    try:
        # ── 启动浏览器（桌面形态）──
        pw, engine = browser_layer.start()
        context = browser_layer.launch(pw, engine, PROFILE_DIR, log=log)
        page = context.pages[0] if context.pages else context.new_page()
        human = Human(
            page,
            typing_delay=tuple(humanize["typingDelayMs"]),
            miss_prob=humanize["missProb"],
        )

        if not ensure_login(page, cfg["runtime"]["loginTimeoutMin"]):
            log.error("登录未就绪，本次中止")
            return

        # ── 阶段 1: 搜索 ──
        safe_goto(page, BING_HOME)
        time.sleep(2)
        pool_size = cfg["search"]["desktopCount"] + (cfg["mobile"]["count"] if cfg["mobile"]["enabled"] else 0) + 10
        query_iter = make_query_iter(collect_query_pool(page, pool_size))
        desktop_done = run_search_session(
            context, page, human, query_iter,
            count=cfg["search"]["desktopCount"], cfg=cfg, tag="PC",
        )

        # ── 阶段 2: 移动端搜索（可选）──
        mobile_done = 0
        if cfg["mobile"]["enabled"]:
            try:
                mobile_done = _run_mobile(pw, engine, cfg, humanize)
            except Exception as e:
                log.error(f"移动端搜索失败: {e}")

        # ── 阶段 3: 任务 ──
        tasks_cfg = cfg["tasks"]
        daily = complete_daily_set(page, human) if tasks_cfg["dailySet"] else 0
        earn = complete_earn_tasks(page, human, tasks_cfg["maxTasks"]) if tasks_cfg["earn"] else 0
        redeemed = collect_redeemable_points(page, human) if tasks_cfg["redeem"] else False

        # ── 汇总 ──
        final_points = read_points(context, page)
        log.info("=" * 60)
        log.info("签到完成! 汇总:")
        log.info(f"  PC 搜索: {desktop_done} 次 | 移动搜索: {mobile_done} 次")
        log.info(f"  Daily Set: {daily} | Earn 任务: {earn} | 领取积分: {'成功' if redeemed else '跳过/未找到'}")
        if final_points is not None:
            log.info(f"  当前积分: {final_points}")
        log.info(f"  日志: {LOG_FILE}")
        mark_done()

        if exit_when_done:
            log.info("已启用 --exit-when-done，自动退出。")
            return
        log.info("浏览器保持开启，可查验积分。按 Ctrl+C 退出。")
        log.info("=" * 60)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        log.info("\n用户中断，正在关闭浏览器...")
    except Exception as e:
        log.error(f"运行异常: {e}", exc_info=True)
        if exit_when_done:
            raise
    finally:
        if context is not None:
            try:
                context.close()
                log.info("浏览器已关闭。")
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


def _run_mobile(pw, engine: str, cfg: dict, humanize: dict) -> int:
    """移动端搜索：独立 profile + iPhone 形态上下文（指纹全套一致，见 browser.py）。
    复用主流程的引擎实例，只新开 context——sync API 同线程仅允许一个引擎进程。"""
    profile = SCRIPT_DIR / cfg["mobile"]["profileDir"]
    log.info("启动移动端搜索（独立 Profile）...")
    context = browser_layer.launch(pw, engine, profile, mobile=True, log=log)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        human = Human(
            page,
            typing_delay=tuple(humanize["typingDelayMs"]),
            miss_prob=humanize["missProb"],
        )
        if not ensure_login(page, cfg["runtime"]["loginTimeoutMin"]):
            log.warning("移动端 Profile 未登录，跳过（首次请在该窗口登录一次）")
            return 0

        safe_goto(page, BING_HOME)
        time.sleep(2)
        query_iter = make_query_iter(collect_query_pool(page, cfg["mobile"]["count"] + 10))
        return run_search_session(context, page, human, query_iter,
                                  count=cfg["mobile"]["count"], cfg=cfg, tag="MOBILE")
    finally:
        context.close()


if __name__ == "__main__":
    main()
