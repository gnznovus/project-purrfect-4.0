"""Versioned, installation-scoped product knowledge and modest WP FAQ retrieval."""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    title: str
    text: str
    source: str
    product_id: str | None = None
    version: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self):
        if not all((self.id, self.title, self.text, self.source)):
            raise ValueError("Evidence must have an ID, title, text and source")


@dataclass(frozen=True, slots=True)
class RegisteredProduct:
    id: str
    version: str
    kind: str
    capabilities: tuple[str, ...]
    evidence: tuple[Evidence, ...]

    def __post_init__(self):
        if not self.id or not self.version or self.kind not in ("plugin", "theme"):
            raise ValueError("Invalid registered product")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Duplicate capabilities")
        if any(item.product_id != self.id or item.version != self.version for item in self.evidence):
            raise ValueError("Product evidence must match registered identity and version")


class SiteKnowledge:
    """Never searches arbitrary inactive or unregistered product knowledge."""

    def __init__(self, products: Iterable[RegisteredProduct] = (),
                 wordpress: Iterable[Evidence] = ()):
        self.products = {}
        for product in products:
            if product.id in self.products:
                raise ValueError("Duplicate product IDs")
            self.products[product.id] = product
        self.wordpress = tuple(wordpress)
        if any(item.product_id is not None for item in self.wordpress):
            raise ValueError("WordPress FAQ evidence cannot claim a product identity")

    def replace_products(self, products: Iterable[RegisteredProduct]) -> None:
        updated = SiteKnowledge(products, self.wordpress)
        self.products = updated.products

    def search(self, query: str, *, product_ids: tuple[str, ...] = (),
               general_wp: bool = False, limit: int = 5) -> tuple[Evidence, ...]:
        if not query.strip() or limit < 1:
            return ()
        if any(pid not in self.products for pid in product_ids):
            return ()
        candidates = [item for pid in product_ids for item in self.products[pid].evidence]
        if general_wp:
            candidates.extend(self.wordpress)
        # Common conversational words must not qualify unrelated evidence.\n        words = set(_words(query)) - _STOPWORDS
        results = []
        for record in candidates:
            title = set(_words(record.title))
            tags = set(_words(" ".join(record.tags)))
            body = set(_words(record.text))
            score = 5 * len(words & tags) + 3 * len(words & title) + len(words & body)
            if score:
                results.append((score, record))
        return tuple(item for _, item in sorted(
            results, key=lambda pair: (-pair[0], pair[1].id),
        )[:limit])


_STOPWORDS = frozenset({\n    "i", "im", "my", "me", "you", "your", "a", "an", "the", "and", "or",\n    "in", "on", "at", "to", "of", "for", "from", "is", "are", "was",\n    "were", "it", "this", "that", "do", "does", "did", "can", "could",\n    "how", "what", "where", "why", "with", "have", "has", "had",\n    "wp", "wordpress", "please", "help", "if", "but", "be",\n})\n\ndef _words(text: str) -> tuple[str, ...]:
    import re
    return tuple(re.findall(r"[\w]+", text.casefold()))


# These are generic, non-invasive user-facing suggestions, not site diagnostics.
EVERYDAY_WORDPRESS = (
    Evidence(
        "wp-editor-basic", "WordPress editor basics",
        "If the Edit option is missing, check whether you are signed in and have "
        "permission to edit that page. Ask a site administrator if uncertain; "
        "do not change roles or permissions yourself.",
        "purrfect://everyday-wordpress/editor", tags=("edit", "page", "editor", "permission"),
    ),
    Evidence(
        "wp-cache-basic", "WordPress display cache",
        "If an edit was saved but the public page looks unchanged, check the page "
        "in a private browser window. Ask the site administrator before clearing "
        "shared caches.", "purrfect://everyday-wordpress/cache",
        tags=("cache", "changes", "page", "refresh"),
    ),
    Evidence(
        "wp-login-basic", "WordPress sign-in basics",
        "Check the site's normal login address and use the site's password reset "
        "flow if available. Never share a password, reset token, or one-time code "
        "in chat.", "purrfect://everyday-wordpress/login",
        tags=("login", "password", "signin"),
    ),
)
