"""
聚焦 Dashboard 的"可领取"区域 —— 找领取按钮。
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
            log("[INFO] 导航到 Dashboard")
            page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # ═══ 直击 "可领取" 区域 ═══
            log("=" * 80)
            log("[核心] '可领取'/'领取' 相关元素的精确 HTML")
            log("=" * 80)
            body_html = page.locator("body").inner_html()
            for kw in ["可领取", "领取"]:
                idx = body_html.find(kw)
                if idx >= 0:
                    start = max(0, idx - 400)
                    end = min(len(body_html), idx + 600)
                    log(f"\n--- '{kw}' 附近 HTML ---")
                    log(body_html[start:end])

            # ═══ 页面文本中定位 "可领取" ═══
            log("=" * 80)
            log("[文本] 含 '可领取' '领取' 的行")
            log("=" * 80)
            body = page.locator("body").inner_text()
            for line in body.split("\n"):
                line = line.strip()
                if line and any(kw in line for kw in ["可领取", "领取"]):
                    log(f"  >> {line[:120]}")

        except Exception as e:
            log(f"\n[ERROR] {e}")
            import traceback
            log(traceback.format_exc())
        finally:
            log("=" * 80)
            log("[DONE]")
            output = "\n".join(results)
            out_path = os.path.join(project_root, "dashboard_scan_result.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"\n[INFO] 结果已写入: {out_path}")
            context.close()


if __name__ == "__main__":
    main()
