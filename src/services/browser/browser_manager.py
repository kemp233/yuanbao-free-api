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
    _lock = asyncio.Lock()  # 修正：Lock 必须大写

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
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
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
            # 只要 DOM 出来了就认为加载完成
            await self.page.goto(settings.page_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            logger.info("[Browser] 页面加载完成")
        except Exception:
            logger.warning("[Browser] 页面加载超时，尝试继续执行逻辑")

    async def login(self) -> Dict:
        """执行登录流程"""
        await self.ensure_browser()

        try:
            # 1. 精准锁定包含二维码的那个“内容框” (根据你的 F12 截图)
            # 尝试多种可能的容器选择器
            content_selector = ".hyc-login__content, .t-dialog__body, .t-dialog"
            login_content = self.page.locator(content_selector).first

            # 2. 等待容器可见
            # 只要这个黑灰色的登录框出来了，我们就认为可以截图了
            await login_content.wait_for(state="visible", timeout=10000)
            logger.info("[Browser] 登录面板已就绪")

            # 3. 关键：额外等待 4 秒给二维码加载时间
            # 腾讯的二维码是通过 JS 异步加载的，面板出来了，二维码可能还没画出来
            logger.info("[Browser] 正在等待二维码渲染...")
            await asyncio.sleep(4)

            # 4. 截图
            # 我们直接截取整个 content 容器。OpenCV 会自动从中提取二维码。
            logger.info("[Browser] 正在对登录容器进行截图...")
            await login_content.screenshot(path=settings.qrcode_path)
            logger.info(f"[Browser] 截图保存成功: {settings.qrcode_path}")

            # 5. 调用解码工具
            print_qr_to_terminal(settings.qrcode_path)

            logger.info("[Browser] 请使用微信扫描终端显示的二维码...")

            # 6. 等待登录成功（面板消失）
            try:
                await login_content.wait_for(state="detached", timeout=settings.login_timeout)
                logger.info("[Browser] 扫码成功，面板已关闭")
                self._is_logged_in = True
                return {
                    "success": True,
                    "message": "登录成功",
                    "qrcode_path": settings.qrcode_path
                }
            except Exception:
                logger.warning("[Browser] 等待扫码结果超时")
                return {
                    "success": False,
                    "message": "超时",
                    "qrcode_path": settings.qrcode_path
                }

        except Exception as e:
            # 彻底失败时拍张全屏供调试
            try:
                await self.page.screenshot(path="final_error.png")
            except:
                pass
            logger.error(f"[Browser] 登录逻辑异常: {e}")
            return {"success": False, "message": str(e)}

    async def get_headers(self) -> Optional[Dict]:
        """获取请求头 (捕获 x-uskey)"""
        await self.ensure_browser()
        captured_headers = {}

        async def handle_route(route, request):
            nonlocal captured_headers
            url = request.url
            if settings.header_api_pattern in url:
                headers = request.headers
                if "x-uskey" in headers and not captured_headers.get("x-uskey"):
                    captured_headers = headers
                    logger.info(f"[Browser] 成功捕获请求头: {url}")
            await route.continue_()

        # 先清理旧路由
        try:
            await self.page.unroute("**/*")
        except:
            pass

        await self.page.route("**/*", handle_route)
        self._route_handler = handle_route

        try:
            # 刷新页面以触发 API 请求
            await self.page.reload(timeout=15000, wait_until="domcontentloaded")
            start_time = asyncio.get_event_loop().time()

            # 循环等待请求头捕获
            while (asyncio.get_event_loop().time() - start_time) < settings.header_timeout:
                if captured_headers.get("x-uskey"):
                    break
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"[Browser] 获取 Headers 过程出错: {e}")
        finally:
            if self._route_handler:
                try:
                    await self.page.unroute("**/*")
                    self._route_handler = None
                except:
                    pass

        return captured_headers if captured_headers.get("x-uskey") else None

    async def get_cookies(self) -> Dict[str, str]:
        """获取当前 Context 的 Cookies"""
        await self.ensure_browser()
        if not self.page:
            return {}
        cookies = await self.page.context.cookies()
        return {c["name"]: c["value"] for c in cookies}

    async def close(self):
        """完全关闭浏览器资源"""
        async with self._lock:
            if self.page:
                await self.page.close()
                self.page = None
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None


# 全局单例
browser_manager = BrowserManager()
