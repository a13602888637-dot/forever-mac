"""Explicit installer. Default is a dry run; never overwrites an existing addon."""
import argparse
from pathlib import Path
import sys

# Also supports `python scripts/install_addons.py` without an editable install.
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def install(game_path: Path, apply=False, link=False, backup_existing=False):
    from backend.addon_platform import AddonPlatform
    from backend.config import Settings
    from backend.platform_io import inside

    platform = AddonPlatform(Settings(mode="live", data_dir=PROJECT / "data", game_path=str(game_path), auto_sync=False))
    game = platform.game()
    target = game / "Interface/AddOns"
    names = []
    for name in ("ForeverAI", "ForeverUI"):
        destination, source = target / name, PROJECT / "addons" / name
        if destination.is_symlink() and destination.resolve() == source.resolve():
            continue
        if destination.exists() or destination.is_symlink():
            if not backup_existing:
                raise ValueError(f"{name} 已存在，拒绝覆盖；请在平台接管并审核更新计划")
            platform.adopt("local-" + name)
        names.append(name)
    if link and names:
        raise ValueError("新安装请使用离线副本与安装计划，不再创建游戏目录到源码的链接")
    plans = [platform.bundled(name) for name in names]
    operations = [f"{name}：备份后复制到 {target / name}" for name in names]
    if apply and plans:
        with platform.lock():
            reviewed = [platform.review(p["id"]) for p in plans]
            for plan in reviewed:
                if not plan["can_apply"]:
                    raise ValueError("；".join(plan["blockers"]))
            state = platform.tx.state()
            changes = []
            for plan in reviewed:
                state["installs"][plan["package_id"]] = {"version": plan["version"], "source": plan["provenance"],
                    "files": plan["files"], "owned": list(plan["directories"])}
                changes.extend(("Interface/AddOns/" + name, inside(platform.root, folder)) for name, folder in plan["directories"].items())
            journal = platform.tx.execute(game, "bundled-install", changes, state)
            from backend.platform_io import write_json
            for plan in plans:
                saved = platform.load_plan(plan["id"])
                saved.update(status="applied", operation_id=journal["id"])
                write_json(platform.root / "plans" / (plan["id"] + ".json"), saved)
    return operations or ["插件已链接到既有源码；未改动游戏文件"]


def main():
    parser = argparse.ArgumentParser(description="安装 ForeverAI 与 ForeverUI（默认仅预览）")
    parser.add_argument("--game-path", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="实际创建插件目录")
    parser.add_argument("--link", action="store_true", help="开发模式软链接；Windows 默认复制更方便")
    parser.add_argument("--backup-existing", action="store_true", help="保留已有目录到时间戳备份，而非覆盖")
    args = parser.parse_args()
    try:
        for operation in install(args.game_path, args.apply, args.link, args.backup_existing):
            print(operation)
        print("安装完成；完整重启客户端后启用插件。" if args.apply else "仅预览；添加 --apply 后执行。")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"安装未完成：{exc}\n")


if __name__ == "__main__":
    main()
