import os
import sys
import time
from playwright.sync_api import sync_playwright

# 确保控制台输出使用 UTF-8 或者适应 Windows 的默认编码，并忽略无法编码的字符
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
except AttributeError:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')

def main():
    # 使用脚本所在目录的上级目录作为项目根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    profile_dir = os.path.join(project_root, "chrome_profile")

    # 浏览器通道（按优先级尝试，兼容不同操作系统）
    browser_channels = ["chrome", None]

    print(f"正在以持久化配置目录启动浏览器: {profile_dir}")

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
                raise RuntimeError("无法启动浏览器：请安装 Chrome 或运行 playwright install chromium")

            # 获取第一个页面
            page = context.pages[0] if context.pages else context.new_page()

            print("正在尝试访问 Bing 搜索页面进行测试...")
            page.goto("https://cn.bing.com")

            print(f"控制成功！网页标题为: {page.title()}")
            print("-" * 50)
            print("【提示】浏览器已成功打开并受控！")
            print("您现在可以像平常一样在该 Chrome 窗口中进行任意操作（如登录网站、搜索等）。")
            print("所有数据（Cookie、登录状态）都会自动保存在 chrome_profile 目录中，下次运行依然保留。")
            print("-" * 50)
            print("正在保持浏览器开启，按 Ctrl+C 可以退出测试脚本...")

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n检测到用户退出指令，正在关闭浏览器...")
        except Exception as e:
            print(f"\n运行中发生异常: {e}")
        finally:
            if 'context' in locals():
                context.close()
                print("浏览器已安全关闭。")

if __name__ == "__main__":
    main()
