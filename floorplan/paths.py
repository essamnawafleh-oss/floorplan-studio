"""Per-user data folder (blocks, add-ons)."""

import os
import sys


def user_dir(*parts: str) -> str:
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FloorPlanStudio")
    else:
        base = os.path.join(os.path.expanduser("~"), ".floorplanstudio")
    path = os.path.join(base, *parts)
    os.makedirs(path, exist_ok=True)
    return path
