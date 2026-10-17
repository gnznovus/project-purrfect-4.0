"""Operator-only publishing command for local prototype; never exposed to Children."""
import argparse
from pathlib import Path

from purrfect.sophira_storage import DurableSophira, decode


def main():
    parser = argparse.ArgumentParser(description="Publish a previously user-approved Sophira knowledge revision")
    parser.add_argument("package", type=Path, help="JSON knowledge package including digest")
    parser.add_argument("--database", default="/var/lib/sophira/knowledge.db")
    parser.add_argument("--approved", action="store_true", help="Operator confirms explicit approval was obtained")
    args = parser.parse_args()
    if not args.approved:
        parser.error("Refusing publication: explicit --approved required")
    package = decode(args.package.read_text(encoding="utf-8"))
    catalog = DurableSophira(args.database)
    try:
        catalog.publish_approved(package, approved=True)
    finally:
        catalog.close()
    print(f"Published {package.product_id}@{package.product_version} knowledge revision {package.revision}")


if __name__ == "__main__":
    main()
