"""Bounded, revision-aware lexical retrieval cache.

Only approved Sophia evidence is cached; no generated responses or sessions.
"""
import threading
from collections import OrderedDict
from purrfect.sophira import KnowledgeItem, KnowledgePackage


class RetrievalCache:
    def __init__(self, max_entries: int = 512) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._values: OrderedDict[tuple, tuple[KnowledgeItem, ...]] = OrderedDict()
        self._lock = threading.RLock()

    def lookup(self, tenant: str, product_id: str, package: KnowledgePackage,
               query: str, retrieve) -> tuple[KnowledgeItem, ...]:
        # The checksum covers content, version, and approved revision.
        key = (tenant, product_id, package.product_version, package.digest, query.casefold().strip())
        with self._lock:
            if key in self._values:
                self._values.move_to_end(key)
                return self._values[key]
        result = tuple(retrieve(package, query))
        with self._lock:
            self._values[key] = result
            self._values.move_to_end(key)
            while len(self._values) > self._max_entries:
                self._values.popitem(last=False)
        return result

    @property
    def size(self):
        with self._lock:
            return len(self._values)
