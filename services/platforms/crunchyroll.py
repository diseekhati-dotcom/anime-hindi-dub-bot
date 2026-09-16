from .base import BasePlatform, contains_lang
from .common import clean_language_list
from services.models import PlatformResult, Season

class Crunchyroll(BasePlatform):
    name = "Crunchyroll"
    domains = ["crunchyroll.com"]

    def parse(self, title, text, url):
        # Positive result requires the title plus a recognizable audio/language
        # or episode signal on a Crunchyroll-owned page.
        if title.lower() not in text.lower():
            return self._unknown()
        signals = ["episodes", "episode", "season", "watch", "audio"]
        if not any(s in text.lower() for s in signals):
            return self._unknown()
        return PlatformResult(
            name=self.name, status="Available", audio=clean_language_list(text),
            subtitles=clean_language_list(text), region="India", watch_url=url,
            evidence_url=url
        )
