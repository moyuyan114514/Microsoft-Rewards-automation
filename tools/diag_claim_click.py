"""诊断：点击"可领取"卡片后到底发生什么。

复刻 rewards_bot.collect_redeemable_points 的定位方式，
打印命中元素的完整标签信息，点击后观察页面变化。
只写 dashboard_claim_diag.txt，不改任何状态。
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="ignore")

from playwright.sync_api import sync_playwright

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
profile_dir = os.path.join(project_root, "edge_profile")
results = []


def log(msg: str):
    print(msg, flush=True)
    results.append(msg)


def describe(locator, levels_up=0):
    """打印定位器命中元素自身 + 向上 levels_up 层的关键信息"""
    out = []
    el = locator
    chain = [el]
    for _ in range(levels_up):
        el = el.locator("xpath=..")
        chain.append(el)
    for depth, e in enumerate(reversed(chain)):
        try:
            tag = e.evaluate("el => el.tagName.toLowerCase()")
            cls = (e.get_attribute("class") or "")[:160]
            role = e.get_attribute("role") or ""
            href = e.get_attribute("href") or ""
            aria = e.get_attribute("aria-label") or ""
            onclick = e.get_attribute("onclick") or ""
            out.append(
                f"  [上溯{depth}] <{tag}> role={role!r} href={href!r} aria={aria!r} onclick={onclick!r}\n"
                f"            class={cls}"
            )
        except Exception as ex:
            out.append(f"  [上溯{depth}] 读取失败: {ex}")
    return "\n".join(out)


def read_claim_amount(page):
    try:
        els = page.locator("p.text-labelControl:has-text('可领取')")
        if els.count() == 0:
            return "(卡片不存在)"
        label = els.first
        card = label
        for _ in range(6):
            card = card.locator("xpath=..")
            cls = card.get_attribute("class") or ""
            if "hover" in cls and ("card" in cls.lower() or "cursor-pointer" in cls):
                break
        amount_el = card.locator("p.text-pageHeader").first
        return amount_el.inner_text().strip() if amount_el.is_visible() else "(数量不可见)"
    except Exception as e:
        return f"(读取失败: {e})"


def main():
    context = None
    with sync_playwright() as p:
        for ch in ["msedge", "chrome", None]:
            try:
                kwargs = dict(user_data_dir=profile_dir, headless=False,
                              no_viewport=True, args=["--start-maximized"])
                if ch is not None:
                    kwargs["channel"] = ch
                context = p.chromium.launch_persistent_context(**kwargs)
                break
            except Exception:
                continue
        if context is None:
            raise RuntimeError("无法启动浏览器")
        page = context.pages[0] if context.pages else context.new_page()

        try:
            log("[1] 打开 Dashboard")
            page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            time.sleep(6)

            log(f"[2] 点击前 可领取数量: {read_claim_amount(page)}")

            label = page.locator("p.text-labelControl:has-text('可领取')").first
            if not label.is_visible():
                log("[!] 未找到'可领取'标签，结束")
                return

            # 复刻 rewards_bot 的向上找卡逻辑
            card = label
            matched = False
            for i in range(6):
                card = card.locator("xpath=..")
                cls = card.get_attribute("class") or ""
                log(f"[3] 上溯第{i + 1}层 class 前80字符: {cls[:80]}")
                if "hover" in cls and ("card" in cls.lower() or "cursor-pointer" in cls):
                    matched = True
                    break
            log(f"[3] 命中匹配层: {matched}")
            log("[3] 命中元素及其父链:")
            log(describe(card, 3))

            log("[4] 点击卡片...")
            card.click(timeout=10000)
            time.sleep(4)

            # 点击后页面状态
            log(f"[5] 点击后 URL: {page.url}")
            log(f"[5] 点击后 可领取数量: {read_claim_amount(page)}")

            dialogs = page.locator("[role='dialog'], [role='menu'], [data-state='open']").count()
            log(f"[5] dialog/menu/open 元素数量: {dialogs}")
            for d in page.locator("[role='dialog'], [data-state='open']").all()[:3]:
                try:
                    txt = d.inner_text()[:300].replace("\n", " | ")
                    log(f"    弹层内容: {txt}")
                except Exception:
                    pass

            # 页面上含"领取"的可点击元素
            for el in page.locator("button, a, [role='button']").all():
                try:
                    if not el.is_visible():
                        continue
                    t = (el.inner_text() or "").strip()
                    if "领取" in t and len(t) < 30:
                        log(f"    可点击'领取'元素: <{el.evaluate('e=>e.tagName.toLowerCase()')}> {t!r}")
                except Exception:
                    continue

            shot = os.path.join(project_root, "claim_after_click.png")
            page.screenshot(path=shot)
            log(f"[6] 截图: {shot}")

        except Exception as e:
            log(f"[ERROR] {e}")
            import traceback
            log(traceback.format_exc())
        finally:
            log("[DONE]")
            with open(os.path.join(project_root, "dashboard_claim_diag.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(results))
            context.close()


if __name__ == "__main__":
    main()
