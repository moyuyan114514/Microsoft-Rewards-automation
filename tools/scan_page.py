import os
import sys
import time
from playwright.sync_api import sync_playwright

# 确保控制台输出使用 UTF-8 或者适应 Windows 的默认编码，并忽略无法编码的字符
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
except AttributeError:
    # 兼容低版本 Python
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    profile_dir = os.path.join(project_root, "chrome_profile")

    # 浏览器通道（按优先级尝试）
    browser_channels = ["chrome", None]

    print(f"正在启动受控浏览器: {profile_dir}")

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

            # 获取页面并访问 Bing
            page = context.pages[0] if context.pages else context.new_page()
            print("正在载入 Bing 搜索页面...")
            page.goto("https://cn.bing.com")

            # 等待 DOM 加载完成以确保结构就绪
            page.wait_for_load_state("domcontentloaded")

            print("\n" + "="*80)
            print("[INFO] 页面扫描开始：BING 搜索首页关键元素分析")
            print("="*80)
            print(f"当前页面标题: {page.title()}")
            print(f"当前页面网址: {page.url}")
            print("-"*80)

            # 1. 扫描所有的输入框 (Input / Textarea)
            print("\n[INPUT] 输入框元素 (Inputs/Textareas)")
            inputs = page.locator("input, textarea").all()
            print(f"{'标签类型':<10} | {'ID':<15} | {'Name':<12} | {'Type':<12} | {'Placeholder/描述':<30}")
            print("-" * 90)
            for item in inputs:
                if item.is_visible():
                    tag = item.evaluate("el => el.tagName.toLowerCase()")
                    elem_id = item.get_attribute("id") or "无"
                    name = item.get_attribute("name") or "无"
                    elem_type = item.get_attribute("type") or "text"
                    placeholder = item.get_attribute("placeholder") or item.get_attribute("aria-label") or "无"
                    placeholder = placeholder[:28] + ".." if len(placeholder) > 28 else placeholder
                    print(f"{tag:<10} | {elem_id:<15} | {name:<12} | {elem_type:<12} | {placeholder:<30}")

            # 2. 扫描所有的按钮 (Buttons)
            print("\n[BUTTON] 按钮元素 (Buttons/Clickables)")
            buttons = page.locator("button, input[type='button'], input[type='submit'], label[id*='search'], div[role='button']").all()
            print(f"{'标签/角色':<12} | {'ID':<15} | {'Text/Aria-Label':<35} | {'是否可见':<10}")
            print("-" * 80)
            for item in buttons:
                try:
                    is_visible = item.is_visible()
                    if is_visible:
                        tag = item.evaluate("el => el.tagName.toLowerCase()")
                        role = item.get_attribute("role") or "无"
                        tag_desc = f"{tag}(role={role})" if role != "无" else tag
                        elem_id = item.get_attribute("id") or "无"
                        text = item.inner_text().strip() or item.get_attribute("value") or item.get_attribute("aria-label") or "无"
                        text = text.replace("\n", " ")
                        text = text[:33] + ".." if len(text) > 33 else text
                        print(f"{tag_desc:<12} | {elem_id:<15} | {text:<35} | {'是':<10}")
                except Exception:
                    continue

            # 3. 扫描一些重要的导航和登录链接
            print("\n[LINK] 导航与状态元素 (Key Links)")
            links = page.locator("a[id*='login'], a[id*='user'], a[id*='nav'], a[class*='nav'], a.id_link, li[id*='tab']").all()
            print(f"{'元素类型':<10} | {'ID':<15} | {'链接文本':<30} | {'跳转链接 (Href)':<30}")
            print("-" * 90)
            for item in links:
                if item.is_visible():
                    tag = item.evaluate("el => el.tagName.toLowerCase()")
                    elem_id = item.get_attribute("id") or "无"
                    text = item.inner_text().strip() or "无"
                    href = item.get_attribute("href") or "无"
                    href = href[:28] + ".." if len(href) > 28 else href
                    print(f"{tag:<10} | {elem_id:<15} | {text:<30} | {href:<30}")

            print("\n" + "="*80)
            print("[SUCCESS] 页面扫描完成！浏览器正在保持开启状态...")
            print("您可以在当前 Chrome 窗口中继续操作。")
            print("="*80)

            # 保持开启
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n正在安全关闭浏览器...")
        except Exception as e:
            print(f"\n执行扫描时发生异常: {e}")
        finally:
            if 'context' in locals():
                context.close()
                print("浏览器关闭。")

if __name__ == "__main__":
    main()
