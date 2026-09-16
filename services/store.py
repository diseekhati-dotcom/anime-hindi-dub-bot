import json, os, threading

PATH = os.getenv("FOLLOW_DB", "follows.json")

class FollowStore:
    def __init__(self):
        self.lock = threading.Lock()
        try:
            with open(PATH, "r", encoding="utf-8") as f: self.data = json.load(f)
        except Exception:
            self.data = {"follows": {}, "notifications": {}}

    def _save(self):
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def follow(self, user_id, title):
        with self.lock:
            self.data["follows"].setdefault(str(user_id), [])
            if title not in self.data["follows"][str(user_id)]:
                self.data["follows"][str(user_id)].append(title)
            self._save()

    def unfollow(self, user_id, title):
        with self.lock:
            arr = self.data["follows"].get(str(user_id), [])
            self.data["follows"][str(user_id)] = [x for x in arr if x.lower() != title.lower()]
            self._save()

    def all_follows(self):
        for uid, titles in self.data["follows"].items():
            for title in titles:
                yield int(uid), title

    def should_notify(self, user_id, title, key):
        return self.data["notifications"].get(f"{user_id}:{title}") != key

    def mark_notified(self, user_id, title, key):
        with self.lock:
            self.data["notifications"][f"{user_id}:{title}"] = key
            self._save()
