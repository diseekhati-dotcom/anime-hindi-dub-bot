from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class PlatformResult:
    name: str
    region: str = "India"
    status: str = "❓ Unable to verify"
    audio: List[str] = field(default_factory=list)
    subtitles: List[str] = field(default_factory=list)
    access: Optional[str] = None
    watch_url: Optional[str] = None
    evidence_url: Optional[str] = None
    note: Optional[str] = None

@dataclass
class Season:
    name: str
    planned: Optional[int] = None
    released: Optional[int] = None
    hindi: Optional[int] = None
    english: Optional[int] = None
    japanese: Optional[int] = None
    next_hindi: Optional[str] = None
    next_english: Optional[str] = None
    next_japanese: Optional[str] = None

@dataclass
class AnimeResult:
    title: str
    kind: str = "anime"
    status: str = "Unknown"
    platforms: List[PlatformResult] = field(default_factory=list)
    seasons: List[Season] = field(default_factory=list)
    release_date: Optional[str] = None
    runtime: Optional[str] = None
    franchise: Optional[str] = None
    watch_order: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    verified: bool = False

    def notification_key(self):
        bits = [self.title, self.status]
        for p in self.platforms:
            bits += [p.name, p.status, ",".join(p.audio)]
        for s in self.seasons:
            bits += [s.name, str(s.released), str(s.hindi), str(s.next_hindi)]
        return "|".join(bits)

    def to_telegram_text(self, checked_at: str):
        if self.kind == "movie":
            return self._movie_text(checked_at)
        return self._anime_text(checked_at)

    def _anime_text(self, checked_at):
        lines = [f"🎬 {self.title}", "", f"📌 Status: {self.status}", "", "📺 Available platforms:"]
        available = [p for p in self.platforms if p.status == "Available"]
        uncertain = [p for p in self.platforms if p.status != "Available"]
        if not available and not uncertain:
            lines.append("• ❓ No platform verification result")
        for p in available + uncertain:
            lines += [f"• {p.name} — {p.region}"]
            if p.audio: lines.append("  Audio: " + ", ".join(p.audio))
            if p.subtitles: lines.append("  Subtitles: " + ", ".join(p.subtitles))
            if p.access: lines.append("  Access: " + p.access)
            lines.append(f"  Status: {p.status}")
        if self.seasons:
            lines += ["", "🎞 Season details:"]
            for s in self.seasons:
                lines.append(f"• {s.name}")
                if s.planned is not None: lines.append(f"  Planned: {s.planned} episodes")
                if s.released is not None: lines.append(f"  Released: {s.released}/{s.planned or '?'} episodes")
                if s.hindi is not None: lines.append(f"  Hindi dub: {s.hindi} episodes")
                if s.english is not None: lines.append(f"  English dub: {s.english} episodes")
                if s.japanese is not None: lines.append(f"  Japanese audio: {s.japanese} episodes")
                if s.next_japanese: lines.append(f"  Next Japanese episode: {s.next_japanese}")
                if s.next_english: lines.append(f"  Next English episode: {s.next_english}")
                if s.next_hindi: lines.append(f"  Next Hindi episode: {s.next_hindi}")
        lines += ["", f"⏱ Last checked:", checked_at]
        return "\n".join(lines)

    def _movie_text(self, checked_at):
        lines = [
            f"🎥 Movie: {self.title}", "",
            "📌 Type: Anime Movie",
            "📍 Region: India",
            f"📊 Status: {self.status}", "",
            "📺 Available platforms:"
        ]
        for p in self.platforms:
            lines += [f"", f"• {p.name}"]
            if p.audio: lines.append("  Audio: " + ", ".join(p.audio))
            if p.subtitles: lines.append("  Subtitles: " + ", ".join(p.subtitles))
            if p.access: lines.append("  Access: " + p.access)
            lines.append(f"  Status: {p.status}")
        if self.release_date: lines += ["", f"📅 Release date: {self.release_date}"]
        if self.runtime: lines.append(f"🎞 Runtime: {self.runtime}")
        if self.franchise: lines.append(f"🎬 Franchise: {self.franchise}")
        if self.watch_order: lines.append(f"🔢 Watch order: {self.watch_order}")
        lines += ["", "🌐 Dub details:"]
        audio = {x.lower() for p in self.platforms for x in p.audio}
        lines.append(f"• Hindi dub: {'Available' if any('hindi' in x for x in audio) else '❓ Unable to verify'}")
        lines.append(f"• English dub: {'Available' if any('english' in x for x in audio) else '❓ Unable to verify'}")
        lines.append(f"• Japanese audio: {'Available' if any('japanese' in x for x in audio) else '❓ Unable to verify'}")
        links = [p for p in self.platforms if p.watch_url and p.status == "Available"]
        if links:
            lines += ["", "🔗 Official watch links:"]
            for p in links: lines.append(f"• {p.name}: {p.watch_url}")
        lines += ["", "⏱ Last checked:", checked_at]
        return "\n".join(lines)
