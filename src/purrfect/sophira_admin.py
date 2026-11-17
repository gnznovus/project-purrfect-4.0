"""Trusted operator CLI for approved Sophia knowledge."""
import argparse
from pathlib import Path
from purrfect.sophira_storage import DurableSophira, decode

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--database", default="./sophia.db")
    parser.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    if not args.approved:
        parser.error("Explicit --approved is required")
    package = decode(args.package.read_text(encoding="utf-8"))
    catalog = DurableSophira(args.database)
    try:
        catalog.publish_approved(package, approved=True)
    finally:
        catalog.close()
    print(f"Published {package.product_id}@{package.product_version} revision {package.revision}")

if __name__ == "__main__":
    main()
