import asyncio
from playwright.async_api import async_playwright
from services.models import AnimeResult
from services.title_resolver import resolve_title
from services.cache import TTLCache
from services.platforms.crunchyroll import Crunchyroll
from services.platforms.generic import GenericPlatform

PLATFORMS = [
    ("Crunchyroll", ["crunchyroll.com"]),
    ("Netflix", ["netflix.com"]),
    ("Amazon Prime Video", ["primevideo.com", "amazon.com"]),
    ("Anime Times", ["amazon.com", "primevideo.com"]),
    ("JioHotstar", ["hotstar.com", "jiohotstar.com"]),
    ("MX Player", ["mxplayer.in"]),
    ("ZEE5", ["zee5.com"]),
    ("Muse India / Muse Asia", ["youtube.com"]),
    ("Ani-One India / Ani-One Asia", ["youtube.com"]),
    ("Crunchyroll Channel", ["youtube.com"]),
]

class BrowserManager:
    def __init__(self):
        self.pw = None
        self.browser = None

    async def start(self):
        if not self.browser:
            self.pw = await async_playwright().start()
            self.browser = await self.pw.chromium.launch(headless=True)

    async def stop(self):
        if self.browser: await self.browser.close()
        if self.pw: await self.pw.stop()

    async def new_page(self):
        await self.start()
        page = await self.browser.new_page(
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
        )
        return page

class AnimeDubChecker:
    def __init__(self):
        self.browser = BrowserManager()
        self.cache = TTLCache(1800)

    async def check(self, title, force=False):
        key = title.strip().lower()
        if not force:
            cached = self.cache.get(key)
            if cached:
                return cached
        resolved = await resolve_title(title)
        result = AnimeResult(title=resolved["title"], kind=resolved["kind"], status="Unknown")
        tasks = []
        for name, domains in PLATFORMS:
            if name == "Crunchyroll":
                adapter = Crunchyroll(self.browser)
            else:
                adapter = GenericPlatform(self.browser)
                adapter.name = name
                adapter.domains = domains
            tasks.append(adapter.check(result.title, result.kind))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception):
                result.platforms.append(r)
        if any(p.status == "Available" for p in result.platforms):
            result.status = "Available"
            result.verified = True
        else:
            result.status = "Unable to verify"
        self.cache.set(key, result)
        return result
