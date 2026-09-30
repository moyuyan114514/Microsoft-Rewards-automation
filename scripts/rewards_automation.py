import os
import sys
import time
import random
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

    print(f"[INFO] 正在以持久化配置目录启动浏览器: {profile_dir}")

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

            # 获取页面并访问 Microsoft Rewards 控制面板
            page = context.pages[0] if context.pages else context.new_page()

            print("[INFO] 正在载入微软 Rewards 控制面板...")
            page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded")

            # 等待关键面板元素加载就绪（最多等待 25 秒，支持重定向与手动登录）
            print("[INFO] 正在等待页面资源与任务卡片加载...")
            try:
                # 寻找每日活动卡片所在的 section 或是通用卡片 class
                page.wait_for_selector("#dailyset, .daily-set-card, a.rounded-cornerCardDefault", timeout=25000)
            except Exception:
                print("[WARNING] 等待任务卡片超时，可能需要你手动登录账号。请在打开的 Chrome 窗口中检查状态。")

            # 稳定延时，获取最新的标题与 URL
            time.sleep(3)
            try:
                print(f"[INFO] 当前页面标题: {page.title()}")
                print(f"[INFO] 当前页面网址: {page.url}")
            except Exception:
                print("[WARNING] 读取页面标题或 URL 失败，继续进行元素解析...")

            print("\n" + "="*80)
            print("[STATUS] 开始检测每日活动任务 (Daily Set)...")
            print("="*80)

            # 定位每日活动栏目 (#dailyset) 内的 3 个可点击任务卡片
            # 经页面结构分析，这三个卡片是位于 #dailyset 内的 a.rounded-cornerCardDefault 元素
            # 或者是 href 中含有 search?q= 的 a 元素
            daily_tasks = page.locator("#dailyset a.rounded-cornerCardDefault, #dailyset a[href*='search?q=']").all()

            # 滤除重复的元素（有些选择器可能会覆盖重叠）
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

            # 微软 Rewards 的"每日活动"通常包含刚好 3 个任务卡片
            print(f"[INFO] 精确匹配到未完成/可执行的每日任务卡片数量: {len(unique_tasks)} 个\n")

            if len(unique_tasks) == 0:
                print("[WARNING] 未找到任何符合选择器的任务卡片！请检查你是否已经手动完成了今日的任务。")
                print("如果还有未完成的任务，你可以直接在浏览器窗口中点击，或者在这里按 Ctrl+C 关闭脚本。")
                while True:
                    time.sleep(1)

            tasks_run = 0

            # 开始自动遍历点击任务卡片
            for index, task in enumerate(unique_tasks):
                try:
                    # 提取任务卡片的文本内容
                    task_text = task.inner_text().strip().replace('\n', ' ')
                    task_text = task_text[:40] + ".." if len(task_text) > 40 else task_text

                    print(f"\n[TASK {index+1}] 正在处理任务: \"{task_text}\"")

                    # 模拟人类操作延迟
                    delay = random.uniform(1.5, 3.0)
                    print(f"-> 模拟人类操作，随机等待 {delay:.2f} 秒...")
                    time.sleep(delay)

                    print("-> 正在模拟点击卡片，并等待新标签页弹出...")
                    # 点击卡片，捕获自动在新标签页中打开的活动页
                    with page.expect_popup() as popup_info:
                        task.click()

                    # 捕获新标签页
                    new_page = popup_info.value

                    # 等待新标签页的 DOM 加载就绪，非阻塞式等待
                    new_page.wait_for_load_state("domcontentloaded")
                    print(f"-> 新标签页加载成功! 页面标题: \"{new_page.title()}\"")

                    # 随机停留 5 ~ 8 秒，确保微软服务器成功记录你的积分行为
                    stay_time = random.randint(5, 8)
                    print(f"-> 正在保持活动页开启以记录积分，模拟浏览中，停留 {stay_time} 秒...")
                    time.sleep(stay_time)

                    # 自动安全关闭新标签页
                    new_page.close()
                    print(f"-> 已自动关闭活动页，成功完成任务 {index+1}！")
                    tasks_run += 1

                except Exception as e:
                    print(f"[ERROR] 处理任务 {index+1} 时发生异常: {e}")
                    continue

            print("\n" + "="*80)
            print(f"[SUCCESS] 每日任务自动点击全部结束！共成功点击了 {tasks_run} 个任务。")
            print("浏览器正在保持开启状态，你可以直接在右上角查验积分变化！")
            print("="*80)

            # 保持主控制面板开启
            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n正在安全关闭浏览器并退出...")
        except Exception as e:
            print(f"\n自动化控制中发生异常: {e}")
        finally:
            if 'context' in locals():
                context.close()
                print("浏览器已关闭。")

if __name__ == "__main__":
    main()
