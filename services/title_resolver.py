import re

ALIASES = {
    "konosuba": "KonoSuba",
    "re zero": "Re:Zero",
    "rezero": "Re:Zero",
    "your name": "Your Name",
}

MOVIE_HINTS = {"movie", "film", "your name", "a silent voice", "weathering with you"}

async def resolve_title(query: str):
    q = re.sub(r"\s+", " ", query.strip())
    low = q.lower()
    title = ALIASES.get(low, q)
    kind = "movie" if low in MOVIE_HINTS or low.endswith(" movie") else "anime"
    if low.endswith(" movie"):
        title = q[:-6].strip()
    return {"title": title, "kind": kind}
