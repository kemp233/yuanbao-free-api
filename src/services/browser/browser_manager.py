"""浏览器管理器模块"""

import asyncio
import logging
from typing import Dict, Optional

from playwright.async_api import Browser, Page, async_playwright

from src.config import settings
from src.utils.qr_utils import print_qr_to_terminal

logger = logging.getLogger(__name__)


class BrowserManager:
    """浏览器管理器 - 单例模式"""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.browser: Optional[Browser] = None
            self.page: Optional[Page] = None
            self.playwright = None
            self._route_handler = None
            self._is_logged_in = False
            self._initialized = True

    async def ensure_browser(self):
        """确保浏览器已初始化"""
        async with self._lock:
            if self.browser is None or self.page is None:
                await self._init_browser()

    async def _init_browser(self):
        """初始化浏览器"""
        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None:
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

        if self.page is None:
            context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self.page = await context.new_page()
            await self._load_page()

    async def _load_page(self):
        """预加载页面"""
        logger.info("[Browser] 预加载 Yuanbao 页面...")
        try:
            await self.page.goto(settings.page_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            logger.info("[Browser] 页面加载完成")
        except Exception:
            logger.warning("[Browser] 页面加载超时，尝试继续执行")

    async def login(self) -> Dict:
        """执行登录流程"""
        await self.ensure_browser()

        try:
            # 1. 等待登录面板出现
            panel_selector = ".hyc-login__content, .t-dialog__body"
            await self.page.locator(panel_selector).first.wait_for(state="visible", timeout=10000)
            logger.info("[Browser] 登录面板已显示")

            # 2. 【核心修改】直接定位二维码的“容器”
            # 这个容器在 F12 里叫 hyc-wechat-login，它是一个 200x200 的方块
            qr_container_selector = ".hyc-wechat-login, #hyc-wechat-login"
            qr_container = self.page.locator(qr_container_selector).first
            
            # 等待容器加载
            await qr_container.wait_for(state="visible", timeout=10000)
            
            # 给 2 秒时间让容器内部的二维码图片渲染出来
            await asyncio.sleep(2)

            # 3. 对“容器”进行截图，而不是对“图片”截图
            # 这样可以绕过 img 标签可能存在的 hidden 状态
            logger.info("[Browser] 正在截取二维码区域...")
            await qr_container.screenshot(path=settings.qrcode_path)
            logger.info(f"[Browser] 截图保存成功: {settings.qrcode_path}")

            # 4. 调用工具打印
            print_qr_to_terminal(settings.qrcode_path)

            logger.info("[Browser] 请使用微信扫描终端显示的二维码...")

            # 5. 等待登录成功
            try:
                await self.page.locator(panel_selector).first.wait_for(state="detached", timeout=settings.login_timeout)
                logger.info("[Browser] 扫码成功，面板已关闭")
                self._is_logged_in = True
                return {"success": True, "message": "登录成功", "qrcode_path": settings.qrcode_path}
            except Exception:
                logger.warning("[Browser] 等待扫码结果超时")
                return {"success": False, "message": "超时", "qrcode_path": settings.qrcode_path}

        except Exception as e:
            # 调试：如果还是失败，截一张全屏看看
            try:
                await self.page.screenshot(path="login_fail_debug.png")
            except:
                pass
            logger.error(f"[Browser] 登录流程异常: {e}")
            return {"success": False, "message": str(e)}

    # ... 其余 get_headers, get_cookies, close 代码保持不变 ...
    async def get_headers(self) -> Optional[Dict]:
        await self.ensure_browser()
        captured_headers = {}
        async def handle_route(route, request):
            nonlocal captured_headers
            if settings.header_api_pattern in request.url:
                if "x-uskey" in request.headers:
                    captured_headers = request.headers
            await route.continue_()
        try:
            await self.page.unroute("**/*")
        except: pass
        await self.page.route("**/*", handle_route)
        try:
            await self.page.reload(timeout=15000, wait_until="domcontentloaded")
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < settings.header_timeout:
                if captured_headers.get("x-uskey"): break
                await asyncio.sleep(0.1)
        finally:
            try: await self.page.unroute("**/*")
            except: pass
        return captured_headers if captured_headers.get("x-uskey") else None

    async def get_cookies(self) -> Dict[str, str]:
        await self.ensure_browser()
        cookies = await self.page.context.cookies()
        return {c["name"]: c["value"] for c in cookies}

    async def close(self):
        async with self._lock:
            if self.page: await self.page.close(); self.page = None
            if self.browser: await self.browser.close(); self.browser = None
            if self.playwright: await self.playwright.stop(); self.playwright = None

browser_manager = BrowserManager()
