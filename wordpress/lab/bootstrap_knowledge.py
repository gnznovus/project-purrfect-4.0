"""Seed approved *demo fixtures* only into a completely empty Sophia lab catalog.

Never replay fixtures over an existing database: another machine's independently
approved history must remain authoritative.
"""
import os
from pathlib import Path

from purrfect.sophira_storage import DurableSophira, decode


def main():
    root = Path("/workspace/tests/fixtures")
    catalog = DurableSophira(os.environ.get("SOPHIRA_DB_PATH", "/var/lib/sophira/knowledge.db"))
    try:
        current = catalog.latest("mock-translation", "1.0.0")
        if current is not None:
            print(f"Existing Sophia mock translation revision {current}; left untouched")
            return
        for revision in (1, 2, 3):
            package = decode((root / f"sophira-mock-rev{revision}.json").read_text(encoding="utf-8"))
            catalog.publish_approved(package, approved=True)
        print("Initialized new local-only Sophia demo catalog at revision 3")
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
