"""
终极精细扫描 —— 滚动到每个子任务区域，直接看 HTML 里的 CTA 元素。
"""
import os
import sys
import time
import re

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


def main():
    browser_channels = ["msedge", "chrome", None]

    with sync_playwright() as p:
        context = None
        for ch in browser_channels:
            try:
                kwargs = dict(
                    user_data_dir=profile_dir, headless=False,
                    no_viewport=True, args=["--start-maximized"],
                )
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
            page.goto("https://rewards.bing.com/earn/quest/ENWW_pcparent_FY26_BingMonthlyPC_Jun_punchcard",
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # 滚动确保懒加载
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)

            # ─── 找所有 h3 元素（子任务标题）───
            log("=" * 80)
            log("[核心] 每个 h3 及其后续可点击元素")
            log("=" * 80)
            h3s = page.locator("h3").all()
            for i, h3 in enumerate(h3s):
                try:
                    if not h3.is_visible():
                        continue
                    title = h3.inner_text().strip()
                    if not title or len(title) < 5:
                        continue
                    log(f"\n[h3 #{i}] {title[:80]}")

                    # 向上找父容器（border-b 或 pb-4 的 div），在容器内找所有 a/button
                    parent = h3
                    for _ in range(5):
                        try:
                            parent = parent.locator("xpath=..")
                            c = parent.get_attribute("class") or ""
                            if "border-b" in c or "pb-4" in c or "pb-3" in c or "flex-col" in c:
                                break
                        except:
                            break

                    # 在父容器内找所有 a 和 button
                    clickables = parent.locator("a, button").all()
                    for j, el in enumerate(clickables):
                        try:
                            if el.is_visible():
                                t = el.inner_text().strip()
                                tag = el.evaluate("el => el.tagName.toLowerCase()")
                                href = el.get_attribute("href") or ""
                                cls = el.get_attribute("class") or ""
                                if t and t != title:
                                    log(f"  → [{j}] <{tag}> text=\"{t[:40]}\"")
                                    log(f"         href={href[:120]}")
                                    log(f"         class={cls[:80]}")
                        except:
                            pass

                    # 也直接取 parent 的 innerHTML
                    html = parent.inner_html()
                    # 从 html 里提取 a 标签
                    a_tags = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', html)
                    for href, text in a_tags:
                        text = text.strip()
                        if text and text != title and len(text) < 30:
                            # 跳过导航标签
                            if text in ["首页","积分赚取","兑换","关于","邀请好友赚积分","更多活动",
                                         "订单历史记录","常见问题解答","最佳做法","兑换促销代码",
                                         "网站地图","必应","Xbox","关于 Microsoft","公司资讯",
                                         "隐私与 Cookie","使用条款","关于我们的广告","简体中文"]:
                                continue
                            log(f"  → [html] <a> text=\"{text}\" href={href[:120]}")

                    b_tags = re.findall(r'<button[^>]*>([^<]*)</button>', html)
                    for text in b_tags:
                        text = text.strip()
                        if text and text != title and len(text) < 30:
                            log(f"  → [html] <button> text=\"{text}\"")
                except:
                    pass

            # ─── 直接 dump 所有含 "查看" "发现" 的区域的 HTML ───
            log("=" * 80)
            log("[HTML dump] 含 CTA 文字的区域")
            log("=" * 80)
            body_html = page.locator("body").inner_html()
            # 找到 "查看赛程" 等关键词附近的 HTML
            for kw in ["查看赛程", "查看笔记本电脑", "发现优惠", "点击完成", "点击完成任务"]:
                idx = body_html.find(kw)
                if idx >= 0:
                    start = max(0, idx - 300)
                    end = min(len(body_html), idx + 400)
                    log(f"\n--- '{kw}' 附近 HTML ---")
                    log(body_html[start:end])

        except Exception as e:
            log(f"\n[ERROR] {e}")
            import traceback
            log(traceback.format_exc())
        finally:
            log("=" * 80)
            log("[DONE]")
            output = "\n".join(results)
            out_path = os.path.join(project_root, "quest_scan_result.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"\n[INFO] 结果已写入: {out_path}")
            context.close()


if __name__ == "__main__":
    main()
