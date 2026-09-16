from .base import BasePlatform
from .common import clean_language_list
from services.models import PlatformResult

class GenericPlatform(BasePlatform):
    def parse(self, title, text, url):
        # Generic adapters stay conservative. A positive result is only emitted
        # when title and a platform availability signal are both visible.
        low = text.lower()
        if title.lower() not in low:
            return self._unknown()
        signals = ["watch now", "play", "episodes", "season", "available", "stream"]
        if not any(s in low for s in signals):
            return self._unknown()
        langs = clean_language_list(text)
        return PlatformResult(
            name=self.name, status="Available", audio=langs,
            subtitles=langs, region="India", watch_url=url, evidence_url=url
        )
