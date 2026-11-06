"""Official MCP SDK stdio server. AI tools cannot write into the game tree."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .addon_platform import AddonPlatform
from .addon_workshop import Workshop
from .config import Settings
from .db import Database


def create_mcp(settings: Settings):
    db = Database(settings.data_dir / "companion.sqlite3")
    platform = AddonPlatform(settings, lambda: settings.game_path or db.get("game_path"))
    workshop = Workshop(platform)
    mcp = FastMCP("Forever Offline Workshop", instructions="仅支持国服无限。默认只修改工作区副本；安装计划必须在桌面平台查看并点击应用。Lua 检查只编译，不执行。API 缓存可能较旧，运行结果需游戏内验证。")

    @mcp.tool()
    def list_addons() -> dict[str, Any]:
        """只读列出当前客户端插件、包、依赖、来源和兼容事实。"""
        return platform.inventory()

    @mcp.tool()
    def read_addon_source(package_id: str, directory: str, path: str) -> dict[str, Any]:
        """只读已装插件源码。禁止越界路径、符号链接和大文件。"""
        return workshop.read_installed(package_id, directory, path)

    @mcp.tool()
    def list_projects() -> list[dict[str, Any]]:
        """列出离线工作区项目。"""
        return workshop.projects()

    @mcp.tool()
    def create_project(name: str, description: str = "") -> dict[str, Any]:
        """在工作区创建 Forever 插件模板，不安装到游戏。"""
        return workshop.create(name, description)

    @mcp.tool()
    def clone_addon(package_id: str) -> dict[str, Any]:
        """把已装插件包复制到工作区，保留比较基线。"""
        return workshop.clone(package_id)

    @mcp.tool()
    def list_project_files(project_id: str) -> list[dict[str, Any]]:
        """列出项目的源码路径及 SHA256。"""
        return workshop.files(project_id)

    @mcp.tool()
    def read_file(project_id: str, path: str) -> dict[str, Any]:
        """读取工作区 UTF-8 源码以及保存所需的 SHA256。"""
        return workshop.read(project_id, path)

    @mcp.tool()
    def write_file(project_id: str, path: str, content: str, expected_sha256: str | None = None) -> dict[str, Any]:
        """修改工作区源码；已有文件必须提供读取时的 SHA256。"""
        return workshop.write(project_id, path, content, expected_sha256)

    @mcp.tool()
    def query_api(query: str) -> dict[str, Any]:
        """查询带客户端版本与来源的公开 API 缓存；未命中不是缺失证明。"""
        return workshop.api(query)

    @mcp.tool()
    def validate_project(project_id: str) -> dict[str, Any]:
        """仅编译 Lua 5.1、校验 TOC 与文件引用，不执行第三方插件代码。"""
        return workshop.validate(project_id)

    @mcp.tool()
    def diff_project(project_id: str) -> dict[str, Any]:
        """比较工作区文件与创建/复制时的基线，返回统一差异。"""
        return workshop.diff(project_id)

    @mcp.tool()
    def package_project(project_id: str) -> dict[str, Any]:
        """校验并生成带 Forever 发布声明的 ZIP，不修改游戏目录。"""
        return workshop.pack(project_id)

    @mcp.tool()
    def create_install_plan(export_id: str) -> dict[str, Any]:
        """从已打包产物创建可审核安装计划；需在桌面平台点击应用。"""
        return workshop.install_plan(export_id)

    @mcp.tool()
    def project_history(project_id: str) -> list[dict[str, Any]]:
        """列出离线源码修改历史。"""
        return workshop.history(project_id)

    @mcp.tool()
    def revert_workspace_revision(project_id: str, revision: str) -> dict[str, Any]:
        """撤销未被后续覆盖的一次工作区修改，不触碰游戏文件。"""
        return workshop.revert(project_id, revision)

    @mcp.tool()
    def operation_history() -> list[dict[str, Any]]:
        """只读查看桌面平台安装、组合和回滚的操作状态。"""
        return platform.history()

    return mcp
