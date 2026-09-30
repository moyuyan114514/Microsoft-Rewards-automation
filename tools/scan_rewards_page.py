import os
import sys
import time
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    profile_dir = os.path.join(project_root, "chrome_profile")

    # 浏览器通道（按优先级尝试）
    browser_channels = ["chrome", None]

    print(f"[INFO] 正在启动浏览器: {profile_dir}")

    with sync_playwright() as p:
        try:
            # 依次尝试浏览器通道
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
            print("[INFO] 正在加载 Rewards 控制面板...")
            page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded")

            # 稳定等待 5 秒
            print("[INFO] 等待页面渲染...")
            time.sleep(5)

            print(f"[INFO] 页面标题: {page.title()}")
            print(f"[INFO] 页面 URL: {page.url}")

            print("\n" + "="*80)
            print("[SCAN] 开始扫描页面中所有可能与任务相关的元素...")
            print("="*80)

            # 1. 扫描所有含有 rewards 或是 card 字样的类名
            print("\n【关键类名/ID 元素匹配】")
            elements = page.locator("[class*='card'], [class*='set'], [class*='promo'], [id*='set'], [id*='card']").all()
            count = 0
            for el in elements:
                try:
                    if el.is_visible():
                        tag = el.evaluate("el => el.tagName.toLowerCase()")
                        elem_id = el.get_attribute("id") or "无"
                        elem_class = el.get_attribute("class") or "无"
                        text = el.inner_text().strip().split('\n')[0]
                        text = text[:30] + ".." if len(text) > 30 else text
                        if text: # 仅打印有文本的元素
                            print(f"{tag:<8} | ID: {elem_id:<15} | Class: {elem_class:<40} | Text: {text}")
                            count += 1
                            if count >= 30: # 限制打印前 30 个
                                break
                except Exception:
                    continue

            # 2. 扫描所有可能的可点击卡片 (a 标签)
            print("\n【可点击卡片链接 (a tags)】")
            links = page.locator("a").all()
            count = 0
            for l in links:
                try:
                    if l.is_visible():
                        text = l.inner_text().strip().replace('\n', ' ')
                        href = l.get_attribute("href") or "无"
                        elem_class = l.get_attribute("class") or "无"
                        # 查找包含特定关键字或有图标的链接
                        if "rewards" in href or "mee-icon" in l.inner_html() or len(text) > 2:
                            text = text[:25] + ".." if len(text) > 25 else text
                            href = href[:30] + ".." if len(href) > 30 else href
                            print(f"Text: {text:<28} | Href: {href:<32} | Class: {elem_class}")
                            count += 1
                            if count >= 30:
                                break
                except Exception:
                    continue

            print("\n" + "="*80)
            print("[SUCCESS] 扫描结束，浏览器保持开启...")
            print("="*80)

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n退出...")
        finally:
            if 'context' in locals():
                context.close()


if __name__ == "__main__":
    main()
