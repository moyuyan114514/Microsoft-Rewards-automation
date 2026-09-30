"""
扫描 rewards.bing.com/earn 的 DOM 结构，定位 offer 卡片和任务元素。
增强版：自动关闭、深层扫描、多等待策略。
"""
import os
import sys
import time
import json

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

        try:
            # 如果有已登录页面则复用
            page = None
            for pg in context.pages:
                url = pg.url
                if "login" not in url and url != "about:blank":
                    page = pg
                    log(f"[INFO] 复用已有标签页: {url}")
                    break

            if page is None:
                page = context.new_page()
                log("[INFO] 创建新标签页")

            # ─── 第 1 步：先尝试从 Dashboard 确认登录态 ───
            log("=" * 80)
            log("[STEP 1] 导航到 Dashboard 确认登录态")
            log("=" * 80)
            page.goto("https://rewards.bing.com/dashboard", wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)
            log(f"  URL: {page.url}")
            log(f"  标题: {page.title()}")

            # 检查是否已登录
            body_text = page.locator("body").inner_text()
            if "sign" in body_text.lower() and "in" in body_text.lower():
                log("[WARN] 可能未登录，页面含 sign in 文本")
            else:
                log("[ OK ] 看起来已登录")

            # ─── 第 2 步：导航到 Earn 页面 ───
            log("=" * 80)
            log("[STEP 2] 导航到 rewards.bing.com/earn")
            log("=" * 80)
            page.goto("https://rewards.bing.com/earn", wait_until="domcontentloaded", timeout=30000)

            # 分阶段等待：依次尝试不同的等待策略
            wait_ok = False
            for wait_s in [3, 5, 8]:
                log(f"  等待 {wait_s}s 让 JS 渲染...")
                time.sleep(wait_s)
                url_now = page.url
                log(f"  当前 URL: {url_now}")
                if "earn" in url_now:
                    wait_ok = True
                    break

            if not wait_ok:
                log(f"[WARN] 未能稳定在 /earn 页面，当前: {page.url}")

            log(f"  最终页面标题: {page.title()}")
            log(f"  最终页面 URL: {page.url}")

            # ─── 第 3 步：扫描页面整体结构 ───
            log("=" * 80)
            log("[STEP 3] 页面整体结构扫描")
            log("=" * 80)

            # 3a. 所有可见的 <a> 标签
            log("--- 3a. 所有可见 <a> 标签 (href + 文本) ---")
            all_links = page.locator("a").all()
            found = 0
            for el in all_links:
                try:
                    if el.is_visible():
                        text = el.inner_text().strip().replace("\n", " ")[:80]
                        href = el.get_attribute("href") or "(无)"
                        cls = el.get_attribute("class") or ""
                        if text and len(text) > 2:
                            found += 1
                            log(f"  [{found:2d}] href: {href[:90]}")
                            log(f"        text: {text}")
                            log(f"        class: {cls[:70]}")
                except:
                    pass
            log(f"  共 {found} 个可见链接")

            # 3b. 所有可见 <button> 标签
            log("--- 3b. 所有可见 <button> ---")
            buttons = page.locator("button").all()
            b_found = 0
            for el in buttons:
                try:
                    if el.is_visible():
                        text = el.inner_text().strip().replace("\n", " ")[:60]
                        if text:
                            b_found += 1
                            cls = el.get_attribute("class") or "-"
                            aid = el.get_attribute("aria-label") or "-"
                            log(f"  [{b_found:2d}] text: {text}")
                            log(f"        class: {cls[:60]}")
                            log(f"        aria-label: {aid[:50]}")
                except:
                    pass
            log(f"  共 {b_found} 个可见按钮")

            # 3c. 所有含 "点数/point/+5/+10" 的元素
            log("--- 3c. 含积分标记的元素 ---")
            for tag in ["span", "div", "p", "button", "a", "h2", "h3", "label"]:
                try:
                    els = page.locator(tag).all()
                    for el in els:
                        try:
                            if el.is_visible():
                                t = el.inner_text().strip()
                                if any(p in t for p in ["+5", "+10", "+15", "+20", "+30", "+50",
                                                          "point", "Point", "points", "Points",
                                                          "积分", "点数"]):
                                    eid = el.get_attribute("id") or "-"
                                    cls = el.get_attribute("class") or "-"
                                    log(f"  <{tag}> id={eid} class={cls[:50]}")
                                    log(f"        文本: {t[:80]}")
                        except:
                            pass
                except:
                    pass

            # 3d. 扫描所有含 card/set/offer/earn/promo/task 类的元素
            log("--- 3d. Class 含 card/set/offer/earn/promo/task/activity 的元素 ---")
            for cp in ["card", "set", "offer", "earn", "promo", "task", "activity"]:
                try:
                    sel = f"[class*='{cp}']"
                    els = page.locator(sel).all()
                    count = 0
                    for el in els:
                        try:
                            if el.is_visible() and count < 15:
                                tag = el.evaluate("el => el.tagName.toLowerCase()")
                                cls = el.get_attribute("class") or "-"
                                text = el.inner_text().strip().replace("\n", " ")[:60]
                                if text:
                                    count += 1
                                    log(f"  [{count:2d}] <{tag}> .{cp}*  class={cls[:60]}")
                                    log(f"        文本: {text}")
                        except:
                            pass
                except:
                    pass

            # 3e. 扫描 role 属性
            log("--- 3e. [role] 属性元素 ---")
            for role in ["listitem", "list", "button", "dialog", "region", "group", "tab", "tabpanel"]:
                try:
                    els = page.locator(f"[role='{role}']").all()
                    count = 0
                    for el in els:
                        try:
                            if el.is_visible() and count < 8:
                                text = el.inner_text().strip().replace("\n", " ")[:50]
                                if text:
                                    cls = el.get_attribute("class") or "-"
                                    count += 1
                                    log(f"  role={role} class={cls[:50]}")
                                    log(f"        文本: {text}")
                        except:
                            pass
                except:
                    pass

            # 3f. 扫描 <li> 元素
            log("--- 3f. <li> 元素 ---")
            lis = page.locator("li").all()
            li_count = 0
            for el in lis:
                try:
                    if el.is_visible() and li_count < 20:
                        text = el.inner_text().strip().replace("\n", " ")[:50]
                        if text:
                            li_count += 1
                            cls = el.get_attribute("class") or "-"
                            log(f"  [{li_count:2d}] <li> class={cls[:50]}")
                            log(f"        文本: {text}")
                except:
                    pass

            # ─── 第 4 步：尝试点击「更多活动」 ───
            log("=" * 80)
            log("[STEP 4] 扫描 '更多活动' / 'More' 按钮")
            log("=" * 80)
            more_selectors = [
                "button:has-text('More')",
                "button:has-text('更多')",
                "a:has-text('More')",
                "a:has-text('更多')",
                "[aria-label*='More']",
                "[aria-label*='更多']",
                "[class*='more-activity']",
                "[class*='More-activity']",
                "[class*='more']:has-text('More')",
            ]
            for sel in more_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        text = el.inner_text().strip()
                        cls = el.get_attribute("class") or "-"
                        aid = el.get_attribute("aria-label") or "-"
                        log(f"  匹配: {sel}")
                        log(f"        class: {cls}")
                        log(f"        aria-label: {aid}")
                        log(f"        文本: {text}")
                except:
                    pass

            # ─── 第 5 步：尝试点击积分状态区域并扫描弹出 ───
            log("=" * 80)
            log("[STEP 5] 模拟点击积分状态区域 → 扫描弹出侧边栏")
            log("=" * 80)
            click_selectors = [
                "#rewards-status",
                ".rewards-status",
                "[class*='reward-status']",
                "[class*='header-status']",
                "[class*='user-status']",
                "[class*='point']",
                "[aria-label*='rewards']",
                "[aria-label*='Rewards']",
                "[aria-label*='points']",
                "[aria-label*='Points']",
                "span:has-text('point')",
                "span:has-text('点数')",
                "span:has-text('积分')",
            ]
            clicked = False
            for sel in click_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible():
                        text = el.inner_text().strip().replace("\n", " ")[:50]
                        log(f"  尝试点击: {sel}  文本: {text}")
                        el.click()
                        time.sleep(2)
                        clicked = True
                        break
                except:
                    pass

            if clicked:
                log("  点击后扫描新出现的元素...")
                time.sleep(1.5)
                # 扫描弹出来的 dialog/sidebar/flyout
                for sel in ["[role='dialog']", ".flyout", ".drawer", ".side-panel",
                             "[class*='flyout']", "[class*='drawer']", "[class*='side']",
                             "#pointsBreakdown", "[class*='breakdown']"]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible():
                            text = el.inner_text().strip().replace("\n", " ")[:80]
                            cls = el.get_attribute("class") or "-"
                            log(f"  弹出元素: {sel}")
                            log(f"        class: {cls}")
                            log(f"        文本: {text[:120]}")
                    except:
                        pass
            else:
                log("  未找到可点击的积分状态触发区域")

            # ─── 第 6 步：记录关键选择器是否匹配 ───
            log("=" * 80)
            log("[STEP 6] 关键选择器测试")
            log("=" * 80)
            test_selectors = {
                "dailyset": "#dailyset",
                "offer card (data-bi)": "[data-bi-type='earn']",
                "offer card (class)": ".offer-card",
                "earn-offer": ".earn-offer",
                "ds-card": ".ds-card",
                "mee-card": "mee-card",
                "rewards-status": "#rewards-status",
                "rewards-status class": ".rewards-status",
                "points-balance": ".points-balance",
                "redeem-points": "#redeemPoints",
                "redeem-button": ".redeem-button",
            }
            for name, sel in test_selectors.items():
                try:
                    el = page.locator(sel).first
                    visible = el.is_visible()
                    text = (el.inner_text().strip().replace("\n", " ")[:50]
                            if visible else "(不可见)")
                    log(f"  {name:30s} ({sel:35s}) → {'可见' if visible else '不可见'}: {text}")
                except Exception as e:
                    log(f"  {name:30s} ({sel:35s}) → 错误: {str(e)[:50]}")

        except Exception as e:
            log(f"\n[ERROR] 扫描异常: {e}")
            import traceback
            log(traceback.format_exc())
        finally:
            log("=" * 80)
            log("[DONE] 扫描完成，自动关闭浏览器")
            log("=" * 80)
            # 输出最终汇总并写入文件
            output = "\n".join(results)
            print("\n\n=== SCAN_RESULT_SUMMARY ===")
            print(output)
            # 写入工作区文件
            out_path = os.path.join(project_root, "earn_scan_result.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"\n[INFO] 结果已写入: {out_path}")
            context.close()


if __name__ == "__main__":
    main()
