import re
from urllib.parse import quote
from .common import clean_language_list

class BasePlatform:
    name = "Platform"
    domains = []

    def __init__(self, browser):
        self.browser = browser

    async def check(self, title: str, kind: str):
        # Adapter contract: search the live web, open candidate pages, and only
        # return positive availability when platform-owned evidence is visible.
        page = await self.browser.new_page()
        try:
            page.set_default_timeout(5000)
            query = f'site:{self.domains[0]} "{title}"'
            await page.goto("https://www.google.com/search?q=" + quote(query), wait_until="domcontentloaded", timeout=8000)
            links = await page.locator("a").evaluate_all("(els) => els.map(e => e.href).filter(Boolean)")
            candidate = next((u for u in links if any(d in u for d in self.domains)), None)
            if not candidate:
                return self._unknown()
            await page.goto(candidate, wait_until="domcontentloaded", timeout=9000)
            text = (await page.locator("body").inner_text(timeout=5000))[:50000]
            return self.parse(title, text, candidate)
        except Exception as e:
            return self._unknown(str(e))
        finally:
            await page.close()

    def parse(self, title, text, url):
        # Conservative generic parser. Platform-specific adapters override this.
        return self._unknown()

    def _unknown(self, note=None):
        from services.models import PlatformResult
        return PlatformResult(name=self.name, status="❓ Unable to verify", note=note)

def contains_lang(text, lang):
    return bool(re.search(rf"\b{re.escape(lang)}\b", text, re.I))
