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
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    navigation: dict | None = None

    def __post_init__(self):
        if not all((self.id, self.title, self.text, self.source)):
            raise ValueError("Evidence must have an ID, title, text and source")
        if self.parent_id is not None and (not isinstance(self.parent_id, str) or not self.parent_id or self.parent_id == self.id):
            raise ValueError("Invalid evidence parent")
        if not isinstance(self.child_ids, tuple) or any(not isinstance(x, str) or not x or x == self.id for x in self.child_ids) or len(self.child_ids) != len(set(self.child_ids)):
            raise ValueError("Invalid evidence children")
        if self.navigation is not None and (
            not isinstance(self.navigation, dict)
            or set(self.navigation) != {"target_id"}
            or not isinstance(self.navigation["target_id"], str)
            or not self.navigation["target_id"]
        ):
            raise ValueError("Invalid evidence navigation reference")


@dataclass(frozen=True, slots=True)
class TroubleshootingStep:
    id: str
    instruction: str
    evidence_id: str

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in
                   (self.id, self.instruction, self.evidence_id)):
            raise ValueError("Troubleshooting step needs ID, instruction and evidence")


@dataclass(frozen=True, slots=True)
class TroubleshootingProcedure:
    id: str
    title: str
    steps: tuple[TroubleshootingStep, ...]

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip() or not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Troubleshooting procedure needs ID and title")
        if not self.steps or len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("Procedure needs nonempty steps with unique IDs")


@dataclass(frozen=True, slots=True)
class RegisteredProduct:
    id: str
    version: str
    kind: str
    capabilities: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    troubleshooting: tuple[TroubleshootingProcedure, ...] = ()

    def __post_init__(self):
        if not self.id or not self.version or self.kind not in ("plugin", "theme"):
            raise ValueError("Invalid registered product")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Duplicate capabilities")
        if any(item.product_id != self.id or item.version != self.version for item in self.evidence):
            raise ValueError("Product evidence must match registered identity and version")
        if len({p.id for p in self.troubleshooting}) != len(self.troubleshooting):
            raise ValueError("Duplicate troubleshooting procedure IDs")
        evidence_ids = {item.id for item in self.evidence}
        nodes = {item.id: item for item in self.evidence}
        for item in self.evidence:
            if item.parent_id is not None:
                if item.parent_id not in nodes or item.id not in nodes[item.parent_id].child_ids:
                    raise ValueError("Knowledge parent/child link mismatch")
            for child in item.child_ids:
                if child not in nodes or nodes[child].parent_id != item.id:
                    raise ValueError("Knowledge child/parent link mismatch")
            visited = set()
            cursor = item
            while cursor.parent_id is not None:
                if cursor.id in visited:
                    raise ValueError("Knowledge graph contains a parent cycle")
                visited.add(cursor.id)
                cursor = nodes[cursor.parent_id]
        if any(step.evidence_id not in evidence_ids
               for procedure in self.troubleshooting for step in procedure.steps):
            raise ValueError("Troubleshooting step must reference product evidence")


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
        # Common conversational words must not qualify unrelated evidence.
        words = set(_words(query)) - _STOPWORDS
        results = []
        for record in candidates:
            title = set(_words(record.title))
            tags = set(_words(" ".join(record.tags)))
            body = set(_words(record.text))
            score = 5 * len(words & tags) + 3 * len(words & title) + len(words & body)
            if score:
                results.append((score, record))
        ranked = [item for _, item in sorted(results, key=lambda pair: (-pair[0], pair[1].id))]
        if not ranked:
            return ()
        # Traverse immediate relations only, within the authorized product scope.
        by_key = {(item.product_id, item.id): item for item in candidates}
        selected = []
        seen = set()
        for seed in ranked:
            relatives = ([seed.parent_id] if seed.parent_id else []) + list(seed.child_ids)
            for node in [seed] + [by_key.get((seed.product_id, node_id)) for node_id in relatives]:
                if node is None or (node.product_id, node.id) in seen:
                    continue
                selected.append(node)
                seen.add((node.product_id, node.id))
                if len(selected) >= limit:
                    return tuple(selected)
        return tuple(selected)


_STOPWORDS = frozenset({
    "i", "im", "my", "me", "you", "your", "a", "an", "the", "and", "or",
    "in", "on", "at", "to", "of", "for", "from", "is", "are", "was",
    "were", "it", "this", "that", "do", "does", "did", "can", "could",
    "how", "what", "where", "why", "with", "have", "has", "had",
    "wp", "wordpress", "please", "help", "if", "but", "be",
})

def _words(text: str) -> tuple[str, ...]:
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
