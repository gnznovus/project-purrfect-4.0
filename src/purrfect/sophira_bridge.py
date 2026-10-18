"""Local development transport contract for WordPress Child knowledge leasing.

An internal endpoint only. No public publication endpoint or cross-host auth yet.
"""
import json
from dataclasses import replace

from purrfect.knowledge import Evidence, RegisteredProduct, SiteKnowledge
from purrfect.sophira import KnowledgeDelta, KnowledgePackage, SophiraClient
from purrfect.sophira_storage import decode, encode


def sync_request(client: SophiraClient, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"products"} or not isinstance(request["products"], list) or len(request["products"]) > 50:
        raise ValueError("Invalid lease request")
    replies = []
    for product in request["products"]:
        if not isinstance(product, dict) or set(product) != {"id", "version", "revision"}:
            raise ValueError("Invalid product lease request")
        pid, version, revision = product["id"], product["version"], product["revision"]
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (pid, version)) or (
            revision is not None and (type(revision) is not int or revision < 1)
        ):
            raise ValueError("Invalid product lease revision")
        change = client.lease(pid, version, revision)
        if change is None:
            continue
        if isinstance(change, KnowledgePackage):
            replies.append({"type": "snapshot", "product_id": pid, "product_version": version,
                            "payload": json.loads(encode(change))})
        elif isinstance(change, KnowledgeDelta):
            replies.append({"type": "delta", "product_id": pid, "product_version": version,
                            "from_revision": change.from_revision, "to_revision": change.to_revision,
                            "upserts": [vars_for_item(i) for i in change.upserts],
                            "removed_ids": list(change.removed_ids), "target_digest": change.target_digest})
        else:
            raise ValueError("Unsupported Sophira transport response")
    return {"contract_version": 1, "updates": replies}


def vars_for_item(item):
    return {"id": item.id, "content": item.content, "source": item.source, **({"entry_revision": item.entry_revision, "change_note": item.change_note} if item.entry_revision is not None else {})}


def effective_knowledge(knowledge: SiteKnowledge, raw: object) -> SiteKnowledge:
    """Overlay verified active compatible leases; original product stays fallback."""
    if not isinstance(raw, list) or len(raw) > 50:
        return knowledge
    leases = {}
    for value in raw:
        try:
            package = decode(json.dumps(value))
            if package.product_id not in knowledge.products:
                continue
            product = knowledge.products[package.product_id]
            if package.product_version != product.version:
                continue
            leases[product.id] = package
        except (ValueError, TypeError, KeyError):
            continue
    products = []
    for product in knowledge.products.values():
        lease = leases.get(product.id)
        if lease is None:
            products.append(product)
            continue
        existing = {e.id: e for e in product.evidence}
        # Approved knowledge has priority; original product documentation is a fallback
        # and continues to supply troubleshooting step evidence.
        for item in lease.items:
            previous = existing.get(item.id)
            existing[item.id] = Evidence(item.id, previous.title if previous else item.id,
                                         item.content, versioned_source(item.source, product.version, item.entry_revision), product.id, product.version,
                                         previous.tags if previous else ())
        products.append(replace(product, evidence=tuple(existing.values())))
    return SiteKnowledge(products, knowledge.wordpress)


def versioned_source(source: str, product_version: str, entry_revision: int | None) -> str:
    """Display-only provenance. Original source remains stable in leased knowledge."""
    if entry_revision is None:
        return source
    if "://" not in source:
        return f"{source}-r{entry_revision}"
    scheme, path = source.split("://", 1)
    return f"{scheme}-{product_version}://{path}-r{entry_revision}"
