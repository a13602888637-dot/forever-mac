"""Export the already synced records. No extra download and no game interaction."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.catalog_export import export_catalog  # noqa: E402
from backend.db import Database  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="把本地缓存的完整物品和配方灌入 ForeverAI 插件")
    parser.add_argument("--db", type=Path, default=ROOT / "data/companion.sqlite3")
    args = parser.parse_args()
    print(json.dumps(export_catalog(Database(args.db), ROOT / "addons/ForeverAI/CatalogData.lua"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
