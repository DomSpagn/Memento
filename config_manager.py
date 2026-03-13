"""
config_manager.py
Handles reading and writing the Memento configuration file (mem_conf.json).
"""

import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mem_conf.json")


def config_exists() -> bool:
    """Return True if the configuration file already exists on disk."""
    return os.path.isfile(CONFIG_FILE)


def load_config() -> dict:
    """Load and return the configuration dictionary from disk."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    """Persist the configuration dictionary to disk."""
    dir_path = os.path.dirname(CONFIG_FILE)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
