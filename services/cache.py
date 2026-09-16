import time
class TTLCache:
    def __init__(self, ttl):
        self.ttl = ttl
        self.data = {}
    def get(self, key):
        item = self.data.get(key)
        if not item: return None
        if time.time() - item[0] >= self.ttl:
            self.data.pop(key, None)
            return None
        return item[1]
    def set(self, key, value):
        self.data[key] = (time.time(), value)
