"""
humanize.py —— 人类行为模拟层

只用 Playwright 底层输入事件（mouse/keyboard/wheel）实现，零额外依赖。
每个动作都产生与真人一致的"受信任输入事件流"，而非瞬间完成的合成操作。

技术来源（研读的开源项目，详见 README「致谢」）：
  - safarsin/AutoRewarder（src/emulator/human.py，约 570 行的手写模拟）：
      * 二次贝塞尔曲线鼠标轨迹 + smoothstep 缓动（起步慢→中间快→收尾慢）
      * ±2px 微抖动：真人的手不可能像素级精准
      * 小概率"点偏"后自行修正
      * 点击落点在元素矩形内均匀随机，而非几何中心
        （原注释：手指有肉垫，真实点击在目标内部但不完美）
      * 滚动深度分布：70% 浅层浏览 / 30% 滚近底部（依据用户阅读行为统计）
      * 移动过程分段变速停顿 + 偶发犹豫
  - Microsoft-Rewards-Script（ghost-cursor 思路 + BrowserSearch.ts）：
      * 逐键输入，每键 40~110ms 随机间隔，偶发词级停顿
      * 搜索后随机滚动、按概率随机点击结果并停留

与机器人行为的对照：
  locator.click()  → 元素中心瞬间命中，无移动轨迹
  fill(text)       → 整串文本瞬间出现，无任何中间按键事件
  window.scrollTo  → 无滚轮事件、无阅读停顿
"""

import random
import time


def _smoothstep(t: float) -> float:
    """缓入缓出：t∈[0,1]，两端慢中间快"""
    return t * t * (3 - 2 * t)


def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


class Human:
    """把"真人会做的动作"包在 Playwright Page 之上。

    坐标一律使用视口内 client 坐标，与 page.mouse 的坐标系一致。
    """

    def __init__(self, page, typing_delay=(40, 110), miss_prob=0.05):
        """
        Args:
            page: Playwright Page
            typing_delay: 每键间隔毫秒区间 (min, max)
            miss_prob: 鼠标移动"点偏"概率（点偏后会自动修正）
        """
        self.page = page
        self.typing_delay = typing_delay
        self.miss_prob = miss_prob
        # 记忆上一次鼠标位置（视口坐标），轨迹从上次位置自然延续
        self.last_pos = [random.randint(100, 500), random.randint(100, 500)]

    # ── 基础 ──────────────────────────────────────────────────
    def _viewport(self):
        try:
            return self.page.evaluate("() => [window.innerWidth, window.innerHeight]")
        except Exception:
            return [1280, 800]

    def _clamp_point(self, x, y):
        w, h = self._viewport()
        return _clamp(int(x), 0, w - 1), _clamp(int(y), 0, h - 1)

    def pause(self, min_s, max_s):
        time.sleep(random.uniform(min_s, max_s))

    # ── 鼠标 ──────────────────────────────────────────────────
    def move_to(self, locator):
        """沿贝塞尔曲线移动到元素内随机一点。失败抛异常，由调用方决定回退。"""
        box = locator.bounding_box()
        if not box or box["width"] <= 0 or box["height"] <= 0:
            raise ValueError("element has no bounding box")

        inset = 2
        tx = box["x"] + random.uniform(inset, max(inset + 1, box["width"] - inset))
        ty = box["y"] + random.uniform(inset, max(inset + 1, box["height"] - inset))
        self._glide(tx, ty)

        # 小概率先偏到附近一点，再快速修正回来 —— 真人运鼠的典型失误模式
        if random.random() < self.miss_prob:
            self._glide(
                tx + random.randint(-30, 30),
                ty + random.randint(-30, 30),
                steps=random.randint(5, 10),
            )
            self.pause(0.05, 0.2)

    def _glide(self, tx, ty, steps=None):
        """从上一次位置沿二次贝塞尔曲线滑到 (tx, ty)"""
        sx, sy = self._clamp_point(*self.last_pos)
        tx, ty = self._clamp_point(tx, ty)

        dist = ((tx - sx) ** 2 + (ty - sy) ** 2) ** 0.5
        if steps is None:
            # 每 8~15px 一步，距离越远步数越多；总步数限制在 8~45
            steps = _clamp(int(dist / random.uniform(8, 15)), 8, 45)

        # 贝塞尔控制点：在连线中点附近随机偏移；偏移量随距离缩放，避免短距离绕圈
        wobble = max(20.0, min(150.0, dist * 0.35))
        cx = (sx + tx) / 2 + random.uniform(-wobble, wobble)
        cy = (sy + ty) / 2 + random.uniform(-wobble, wobble)

        for i in range(steps + 1):
            t = _smoothstep(i / steps)
            x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * cx + t ** 2 * tx
            y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * cy + t ** 2 * ty
            if i < steps:  # 落点精确，中途抖动
                x += random.randint(-2, 2)
                y += random.randint(-2, 2)
            x, y = self._clamp_point(x, y)
            self.page.mouse.move(x, y, steps=1)

            # 变速停顿：起步快、中段慢、收尾最从容；5% 概率额外犹豫一下
            if i < steps * 0.3:
                self.pause(0.005, 0.02)
            elif i < steps * 0.7:
                self.pause(0.01, 0.04)
            else:
                self.pause(0.02, 0.06)
            if random.random() < 0.05:
                self.pause(0.05, 0.15)

        self.last_pos = [tx, ty]

    def click(self, locator):
        """移过去再按下抬起（真实 down/up 事件）。元素不可定位时回退 locator.click()。"""
        try:
            self.move_to(locator)
            self.pause(0.08, 0.25)  # 看清目标再按
            self.page.mouse.down()
            self.pause(0.02, 0.08)  # 按住时长
            self.page.mouse.up()
            self.pause(0.15, 0.4)
            return True
        except Exception:
            locator.click(timeout=5000)
            return False

    def click_verified(self, locator, retries=2):
        """拟人点击 + 命中校验。

        陷阱：贝塞尔滑行需要 1~3 秒，期间页面 hover 动画可能移动布局，
        盲目在预定坐标 down/up 会点空。因此按下前用 elementFromPoint
        与目标元素做身份比对（指针下方是目标本身或其子元素才算命中）；
        未命中则重新瞄准，重试耗尽后回退 locator.click()
        （Playwright 自带命中校验与自动重试）。

        Returns:
            True=拟人点击命中, False=走了回退
        """
        for _ in range(retries + 1):
            try:
                self.move_to(locator)
                handle = locator.element_handle()
                if handle is None:
                    break
            except Exception:
                break
            x, y = self.last_pos
            try:
                hit = self.page.evaluate(
                    """([el, x, y]) => {
                        const hitEl = document.elementFromPoint(x, y);
                        return !!hitEl && (hitEl === el || el.contains(hitEl) || hitEl.contains(el));
                    }""",
                    [handle, x, y],
                )
            except Exception:
                hit = True  # 校验本身失败时按原计划点击
            if hit:
                self.pause(0.08, 0.25)
                self.page.mouse.down()
                self.pause(0.02, 0.08)
                self.page.mouse.up()
                self.pause(0.15, 0.4)
                return True
            self.pause(0.2, 0.5)  # 布局在动，缓一下再重新瞄准
        locator.click(timeout=5000)
        return False

    # ── 键盘 ──────────────────────────────────────────────────
    def type_text(self, text):
        """逐键输入，随机间隔 + 偶发词级停顿（对照：fill() 是瞬间填充，无按键事件）"""
        lo = self.typing_delay[0] / 1000
        hi = self.typing_delay[1] / 1000
        for ch in text:
            self.page.keyboard.type(ch)
            self.pause(lo, hi)
            if random.random() < 0.03:  # 3% 概率卡壳一下
                self.pause(0.15, 0.4)

    def press(self, key):
        self.page.keyboard.press(key)

    # ── 滚动 ──────────────────────────────────────────────────
    def scroll_page(self, dwell=(3.0, 8.0)):
        """拟人滚动：70% 浅层浏览（页面 10%~50%），30% 滚近底部。

        用 mouse.wheel 发真实滚轮事件，小步快频；对照 window.scrollTo 无滚轮事件。
        """
        if random.random() < 0.7:
            divisor = random.uniform(2, 10)   # 浅层：滚 10%~50%
        else:
            divisor = random.uniform(1, 1.5)  # 深层：滚 67%~100%
        try:
            total = self.page.evaluate("() => document.body.scrollHeight") / divisor
        except Exception:
            return

        scrolled = 0.0
        while scrolled < total:
            step = random.uniform(30, 80)
            self.page.mouse.wheel(0, step)
            scrolled += step
            self.pause(0.03, 0.12)
        self.pause(*dwell)  # "阅读"停顿
