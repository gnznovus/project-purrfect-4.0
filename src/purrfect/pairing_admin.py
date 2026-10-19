"""Trusted operator utility: generate pairing code; never expose code minting over HTTP."""
import argparse
import os
from purrfect.pairing import PairingRegistry

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("issue-code", "revoke"))
    parser.add_argument("--assistant-id")
    parser.add_argument("--ttl", type=int, default=600)
    args = parser.parse_args()
    path = os.environ.get("PURR_PAIRING_DB_PATH")
    if not path:
        parser.error("Set PURR_PAIRING_DB_PATH")
    registry = PairingRegistry(path)
    try:
        if args.operation == "issue-code":
            print(registry.create_pairing_code(ttl_seconds=args.ttl))
        else:
            if not args.assistant_id:
                parser.error("--assistant-id is required for revocation")
            print("Revoked" if registry.revoke(args.assistant_id) else "Not active")
    finally:
        registry.close()

if __name__ == "__main__":
    main()
