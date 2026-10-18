"""Opt-in real WordPress acceptance. Run after Docker lab is installed.

Uses WP-CLI inside Docker; never touches other WordPress sites.
"""
import json
import subprocess
from pathlib import Path

from purrfect.discovery import discover
from purrfect.knowledge import SiteKnowledge

COMPOSE = Path(__file__).with_name("compose.yaml")


def wp(*args: str) -> str:
    command = ["docker", "compose", "-f", str(COMPOSE), "run", "--rm", "-T",
               "cli", "wp", *args]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"WP-CLI failed (exit {result.returncode}): {' '.join(args)}\\n"
            f"STDOUT:\\n{result.stdout.strip()}\\n"
            f"STDERR:\\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def refresh():
    wp("eval", 'purr_child_heartbeat_dirty("registry"); do_action("purrfect/heartbeat_tick");')


def snapshot():
    return json.loads(wp("eval", 'echo wp_json_encode(get_option("purr_child_registry", []));'))


def verify():
    wp("plugin", "activate", "purr-child", "mock-layout", "mock-translation")
    refresh()
    active = discover(snapshot()).products
    assert {p.id for p in active} == {"mock-layout", "mock-translation"}
    knowledge = SiteKnowledge(active)
    assert knowledge.search("edit layout blocks", product_ids=("mock-layout",))
    assert not knowledge.search("translate content", product_ids=("mock-layout",))
    assert knowledge.search("translate content", product_ids=("mock-translation",))

    wp("plugin", "deactivate", "mock-translation")
    refresh()
    active = discover(snapshot()).products
    assert {p.id for p in active} == {"mock-layout"}
    knowledge.replace_products(active)
    assert not knowledge.search("translate", product_ids=("mock-translation",))

    # Restoration leaves both test products available for manual exploration.
    wp("plugin", "activate", "mock-translation")
    refresh()
    assert {p.id for p in discover(snapshot()).products} == {
        "mock-layout", "mock-translation",
    }
    print("LIVE WordPress integration acceptance passed")


if __name__ == "__main__":
    verify()
