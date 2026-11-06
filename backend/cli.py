from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .db import Database
from .paths import discover, import_source
from .references import MCP_TOOLS, References


def main():
    load_dotenv(Path.cwd() / ".env", override=False)
    parser = argparse.ArgumentParser(description="Forever AI Companion · 本地只读助手")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="只在 127.0.0.1 启动中文本地网页")
    serve.add_argument("--mode", choices=("mock", "live"), default=None)
    serve.add_argument("--port", type=int, default=int(os.getenv("FAI_PORT", "18761")))
    inspect = sub.add_parser("inspect", help="发现并验证游戏角色快照，不写入游戏文件")
    inspect.add_argument("--game-path")
    inspect.add_argument("--source-id")
    sub.add_parser("sync-references", help="下载并校验无限图鉴的公开只读资料")
    mcp = sub.add_parser("mcp", help="只调用无限图鉴白名单资料工具")
    mcp.add_argument("--tool", choices=sorted(MCP_TOOLS), required=True)
    mcp.add_argument("--arguments", default="{}", help="JSON 对象，不发送角色快照")
    local_mcp = sub.add_parser("mcp-serve", help="启动本地离线开发 MCP（stdio，无需模型 Key）")
    local_mcp.add_argument("--mode", choices=("mock", "live"), default="live")
    local_mcp.add_argument("--data-dir", type=Path)
    local_mcp.add_argument("--game-path")
    args = parser.parse_args()
    settings = Settings.from_env(getattr(args, "mode", None))
    if args.command == "mcp-serve":
        if args.data_dir:
            settings.data_dir = args.data_dir.expanduser().resolve()
        if args.game_path:
            settings.game_path = args.game_path
    try:
        if args.command == "serve":
            if not 1024 <= args.port <= 65535:
                parser.error("端口应在 1024–65535 之间")
            import uvicorn
            from .web import create_app
            print(f"Forever AI · {settings.mode.upper()} · http://127.0.0.1:{args.port}")
            uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, proxy_headers=False)
        elif args.command == "mcp-serve":
            from .mcp_server import create_mcp
            create_mcp(settings).run(transport="stdio")
        elif args.command == "inspect":
            if args.source_id:
                snapshot = import_source(args.source_id, args.game_path or settings.game_path)
                print(snapshot.model_dump_json(indent=2))
            else:
                print(json.dumps([{"id": s.id, "realm": s.realm, "character": s.character}
                                  for s in discover(args.game_path or settings.game_path)], ensure_ascii=False, indent=2))
        else:
            refs = References(Database(settings.data_dir / "companion.sqlite3"), settings.references_enabled,
                              addon_catalog_path=Path(__file__).resolve().parent.parent / "addons/ForeverAI/CatalogData.lua")
            result = asyncio.run(refs.sync()) if args.command == "sync-references" else asyncio.run(refs.mcp(args.tool, json.loads(args.arguments)))
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as exc:
        parser.exit(1, f"未完成：{exc}\n")


if __name__ == "__main__":
    main()
