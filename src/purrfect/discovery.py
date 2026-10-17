"""Validate inventory from Purr Child; do not trust claimed active registrations."""

from dataclasses import dataclass

from purrfect.knowledge import (Evidence, RegisteredProduct,
                                TroubleshootingProcedure, TroubleshootingStep)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    products: tuple[RegisteredProduct, ...]
    rejected: tuple[str, ...]


def discover(snapshot: dict) -> DiscoveryResult:
    """Validate Child inventory and declared product signals.

    The WordPress Child supplies active installation keys from its own scan.
    A signal is accepted only when its kind and installation key match that
    inventory. This validates consistency, not remote-site authenticity.
    """
    if not isinstance(snapshot, dict) or set(snapshot) != {"active", "signals"}:
        raise ValueError("Expected active inventory and signals")
    active, signals = snapshot["active"], snapshot["signals"]
    if not isinstance(active, list) or not isinstance(signals, list):
        raise ValueError("Invalid inventory")
    valid_active = set()
    for item in active:
        if not isinstance(item, dict) or set(item) != {"kind", "key"}:
            raise ValueError("Invalid active component")
        kind, key = item["kind"], item["key"]
        if kind not in ("plugin", "theme") or not isinstance(key, str) or not key:
            raise ValueError("Invalid active identity")
        valid_active.add((kind, key))
    products, rejected, seen = [], [], set()
    for signal in signals:
        try:
            if not isinstance(signal, dict) or not {
                "kind", "key", "product_id", "version", "contract",
                "capabilities", "knowledge",
            } <= set(signal) or set(signal) - {
                "kind", "key", "product_id", "version", "contract",
                "capabilities", "knowledge", "troubleshooting",
            }:
                raise ValueError("Malformed signal")
            kind, key = signal["kind"], signal["key"]
            pid, version = signal["product_id"], signal["version"]
            if (kind, key) not in valid_active or not all(
                isinstance(s, str) and s.strip() for s in (pid, version, key)
            ) or signal["contract"] != 1 or pid in seen:
                raise ValueError("Inactive, incompatible or duplicate signal")
            capabilities = signal["capabilities"]
            records = signal["knowledge"]
            if not isinstance(capabilities, list) or not isinstance(records, list):
                raise ValueError("Invalid knowledge declaration")
            if any(not isinstance(v, str) or not v.strip() for v in capabilities):
                raise ValueError("Invalid capability")
            evidence = []
            for entry in records:
                if not isinstance(entry, dict) or set(entry) != {
                    "id", "title", "text", "source", "tags",
                } or not isinstance(entry["tags"], list) or any(
                    not isinstance(tag, str) for tag in entry["tags"]
                ):
                    raise ValueError("Invalid evidence")
                evidence.append(Evidence(
                    entry["id"], entry["title"], entry["text"], entry["source"],
                    pid, version, tuple(entry["tags"]),
                ))
            if len({item.id for item in evidence}) != len(evidence):
                raise ValueError("Duplicate evidence IDs")
            procedures_raw = signal.get("troubleshooting", [])
            if not isinstance(procedures_raw, list):
                raise ValueError("Invalid troubleshooting declaration")
            procedures = []
            for entry in procedures_raw:
                if not isinstance(entry, dict) or set(entry) != {"id", "title", "steps"} or not isinstance(entry["steps"], list):
                    raise ValueError("Invalid troubleshooting procedure")
                steps = []
                for step in entry["steps"]:
                    if not isinstance(step, dict) or set(step) != {"id", "instruction", "evidence_id"}:
                        raise ValueError("Invalid troubleshooting step")
                    steps.append(TroubleshootingStep(step["id"], step["instruction"], step["evidence_id"]))
                procedures.append(TroubleshootingProcedure(entry["id"], entry["title"], tuple(steps)))
            product = RegisteredProduct(pid, version, kind, tuple(capabilities),
                                        tuple(evidence), tuple(procedures))
            products.append(product)
            seen.add(pid)
        except (TypeError, ValueError, KeyError) as exc:
            rejected.append(str(exc))
    return DiscoveryResult(tuple(products), tuple(rejected))
