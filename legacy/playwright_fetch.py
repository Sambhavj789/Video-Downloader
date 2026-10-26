import json, re
from playwright.async_api import async_playwright

class PlaywrightFetcher:
    def __init__(self, cdp_url="http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self._pw = None
        self._browser = None
        self._context = None
        self._worker_page = None

    async def connect(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        self._context = self._browser.contexts[0]
        self._worker_page = await self._context.new_page()
        return self._worker_page

    async def fetch_html(self, url):
        await self._worker_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        html = await self._worker_page.content()
        return html

    async def fetch_api_json(self, url, post_data=None):
        await self._worker_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        body = await self._worker_page.content()
        if body.strip().startswith("{"):
            return json.loads(body)
        raise ConnectionError(f"API returned HTML, not JSON (likely blocked): {body[:200]}")

    async def close(self):
        if self._worker_page:
            await self._worker_page.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
