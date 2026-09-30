"""
browser.py —— 浏览器启动层（引擎与通道双回退）

引擎优先级：
  1. patchright —— Playwright 的补丁版：剥离了 Runtime.enable 等运行时注入痕迹，
     微软的自动化检测高度依赖这些痕迹（技术来源见 README「致谢」）
  2. playwright —— 未安装 patchright 时的回退，隐身能力下降但仍可用

浏览器通道（每个引擎内依次尝试）：
  系统安装的 Edge → 系统安装的 Chrome → 补丁版内置 Chromium

设计参考：
  - safarsin/AutoRewarder（emulator/driver.py）：通道回退、移动端 UA/触摸仿真参数
  - Microsoft-Rewards-Script（Browser.ts）：隐身启动参数、locale 一致性

注意：微软 Rewards 会检测无头浏览器，请始终使用有界面模式（headless=False）。
"""

from pathlib import Path

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",  # 移除 navigator.webdriver 标记
    "--no-first-run",
    "--no-default-browser-check",
    "--mute-audio",
    "--disable-dev-shm-usage",
    "--start-maximized",
]

# AutoRewarder 同款移动端 UA：Rewards 以此判定"移动端搜索"配额
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 "
    "Mobile/15E148 Safari/604.1"
)


def _load_engine():
    """加载引擎：patchright 优先，playwright 回退。返回 (sync_playwright, 引擎名)"""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright, "patchright"
    except ImportError:
        pass
    from playwright.sync_api import sync_playwright
    return sync_playwright, "playwright"


def _channel_order(engine: str):
    """按引擎决定通道尝试顺序。

    patchright + 系统 Edge 在访问 rewards/登录页时有已知崩溃 bug
    （playwright 上游 #41438，chiihero 版 README 同样标注其实验性），
    因此 patchright 优先用补丁版内置 Chromium；原生 playwright 无此问题，
    维持 系统 Edge → Chrome → 内置 Chromium。
    """
    if engine == "patchright":
        return [None, "msedge", "chrome"]
    return ["msedge", "chrome", None]


def start():
    """启动引擎进程（进程内全局唯一，可复用它启动多个 context）。

    Returns:
        (pw, engine_name) —— pw 需在所有 context 关闭后调用 pw.stop()
    """
    sync_playwright, engine = _load_engine()
    return sync_playwright().start(), engine


def launch(pw, engine: str, profile_dir, headless=False, mobile=False, log=print):
    """
    在给定引擎上启动持久化上下文浏览器（登录态保存在 profile_dir）。
    同一引擎可多次调用（桌面/移动各一个 context），但不要重复 start()。

    Args:
        pw:          start() 返回的引擎实例
        engine:      引擎名（"patchright" / "playwright"），决定通道顺序
        profile_dir: 用户数据目录（Path 或 str），每个账号独立一个
        headless:    无头模式，Rewards 场景请保持 False
        mobile:      True 时以 iPhone 形态启动（UA/视口/触摸全套一致，
                     供"移动端搜索"使用；对应 AutoRewarder 的 CDP 触摸仿真）
        log:         logger，带 .info/.warning 方法

    Returns:
        (context, engine_name)

    Raises:
        RuntimeError: 所有通道组合均失败
    """
    last_error = None
    for channel in _channel_order(engine):
        label = channel or "内置 Chromium"
        try:
            kwargs = dict(
                user_data_dir=str(profile_dir),
                headless=headless,
                args=STEALTH_ARGS,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            if mobile:
                # 指纹一致性：UA、视口、像素比、触摸必须同时成立，单改 UA 必被识破
                kwargs.update(
                    viewport={"width": 412, "height": 915},
                    device_scale_factor=3,
                    is_mobile=True,
                    has_touch=True,
                    user_agent=MOBILE_USER_AGENT,
                    no_viewport=False,
                )
            else:
                kwargs["no_viewport"] = True
            if channel is not None:
                kwargs["channel"] = channel

            context = pw.chromium.launch_persistent_context(**kwargs)
            log.info(f"  浏览器启动成功 ({engine} / {label})")
            return context
        except Exception as e:
            log.warning(f"  通道 {label} 不可用: {e}")
            last_error = e

    raise RuntimeError(
        f"所有浏览器通道均无法启动。请安装 Edge/Chrome，"
        f"或执行 `playwright install chromium` / `patchright install chromium`。末次错误: {last_error}"
    )
