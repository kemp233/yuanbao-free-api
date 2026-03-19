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
            # 增加一些规避检测的参数
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )

        if self.page is None:
            # 设置视口大小确保元素可见
            self.page = await self.browser.new_page(viewport={'width': 1280, 'height': 800})
            await self._load_page()

    async def _load_page(self):
        """预加载页面"""
        logger.info("[Browser] 预加载 Yuanbao 页面...")
        try:
            await self.page.goto(settings.page_url, timeout=settings.page_timeout)
            # 等待网络空闲，确保脚本加载完成
            await self.page.wait_for_load_state("networkidle")
            
            # 尝试通过 ESC 键关闭可能存在的初始公告/协议弹窗
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(2)
            
            logger.info("[Browser] 页面加载完成")
        except Exception as e:
            logger.error(f"[Browser] 页面加载失败: {e}")
            raise

    async def login(self) -> Dict:
        """执行登录流程，返回二维码信息"""
        await self.ensure_browser()

        try:
            # 1. 检测登录对话框是否已经弹出
            # 腾讯 TDesign 的弹窗通常带有 t-dialog 或 t-portal 类名
            login_dialog_selector = ".t-dialog, .t-portal, [class*='login']"
            is_dialog_visible = await self.page.locator(login_dialog_selector).first.is_visible(timeout=3000)

            if not is_dialog_visible:
                logger.info("[Browser] 未检测到登录框，尝试点击触发登录...")
                # 使用 force=True 强制点击，防止被不可见的遮罩层拦截
                login_trigger = self.page.get_by_role("img").first
                await login_trigger.click(force=True)
                await asyncio.sleep(2)
            else:
                logger.info("[Browser] 登录对话框已在页面显示")

            # 2. 寻找二维码图片
            # 尝试多种可能的选择器（主页面图片、Canvas、或者 iframe 内）
            qr_selectors = [
                "img[src*='qrcode']", 
                ".t-dialog img", 
                "canvas", 
                ".login-qrcode img"
            ]
            
            qrcode_locator = None
            for selector in qr_selectors:
                loc = self.page.locator(selector).first
                if await loc.is_visible(timeout=2000):
                    qrcode_locator = loc
                    logger.info(f"[Browser] 成功通过选择器找到二维码: {selector}")
                    break

            # 如果主页面没找到，尝试原有的 iframe 逻辑
            if not qrcode_locator:
                logger.info("[Browser] 主页面未直接找到二维码，尝试检索 iframe...")
                iframe_frame = self.page.frame_locator("iframe")
                qrcode_locator = iframe_frame.get_by_role("img").first

            # 3. 等待二维码并处理
            await qrcode_locator.wait_for(state="visible", timeout=10000)
            await qrcode_locator.screenshot(path=settings.qrcode_path)
            logger.info(f"[Browser] 二维码已保存至 {settings.qrcode_path}")

            # 打印二维码到终端
            print_qr_to_terminal(settings.qrcode_path)

            logger.info("[Browser] 请扫描终端显示的二维码进行登录...")

            # 4. 等待登录成功（检测登录框消失）
            try:
                # 监测刚才那个对话框消失，认为登录成功
                await self.page.locator(login_dialog_selector).first.wait_for(
                    state="detached", 
                    timeout=settings.login_timeout
                )
                logger.info("[Browser] 扫码成功，登录对话框已关闭")
                self._is_logged_in = True
                return {
                    "success": True,
                    "message": "登录成功",
                    "qrcode_path": settings.qrcode_path,
                }
            except Exception:
                logger.warning("[Browser] 扫码超时或页面未响应登录状态")
                return {
                    "success": False,
                    "message": "扫码超时",
                    "qrcode_path": settings.qrcode_path,
                }

        except Exception as e:
            logger.error(f"[Browser] 登录失败详情: {e}")
            return {
                "success": False,
                "message": f"登录失败: {str(e)}",
            }

    async def get_headers(self) -> Optional[Dict]:
        """获取请求头 (逻辑保持不变)"""
        await self.ensure_browser()
        captured_headers = {}

        async def handle_route(route, request):
            nonlocal captured_headers
            url = request.url
            headers = request.headers

            if settings.header_api_pattern in url:
                if "x-uskey" in headers and not captured_headers.get("x-uskey"):
                    captured_headers = headers
                    logger.info(f"[Browser] 捕获到请求头 from {url}")

            await route.continue_()

        if self._route_handler:
            try:
                await self.page.unroute("**/*")
            except Exception:
                pass

        await self.page.route("**/*", handle_route)
        self._route_handler = handle_route

        try:
            # 刷新页面以触发 API 请求并捕获 headers
            reload_task = asyncio.create_task(self.page.reload(timeout=15000))
            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < settings.header_timeout:
                if captured_headers.get("x-uskey"):
                    break
                await asyncio.sleep(0.1)

            if captured_headers.get("x-uskey"):
                if not reload_task.done():
                    reload_task.cancel()
            
        except Exception as e:
            logger.error(f"[Browser] 获取请求头失败: {e}")
        finally:
            if self._route_handler:
                try:
                    await self.page.unroute("**/*")
                    self._route_handler = None
                except Exception:
                    pass

        return captured_headers if captured_headers.get("x-uskey") else None

    async def get_cookies(self) -> Dict[str, str]:
        """获取 Cookie"""
        await self.ensure_browser()
        if not self.page:
            return {}
        cookies = await self.page.context.cookies()
        return {c["name"]: c["value"] for c in cookies}

    async def close(self):
        """关闭浏览器"""
        async with self._lock:
            tasks = []
            if self.page:
                tasks.append(self.page.close())
                self.page = None
            if self.browser:
                tasks.append(self.browser.close())
                self.browser = None
            if self.playwright:
                tasks.append(self.playwright.stop())
                self.playwright = None
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


# 全局单例
browser_manager = BrowserManager()
