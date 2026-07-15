"""mubu 包 — 命令行入口（argparse 子命令 + 日志配置）。"""

import sys
import json
import logging
import getpass
import argparse
from typing import Dict, List, Any

from mubu.config import (
    logger,
    MAX_SEARCH_DEPTH,
    MAX_SEARCH_LIMIT,
    _safe_local_path,
)
from mubu.client import MubuClient
from mubu.convert import (
    markdown_to_doc,
    doc_to_opml,
    doc_to_freeplane,
    export_markdown,
    format_list,
    format_search,
)


def _configure_logging(verbose: bool) -> None:
    """配置 mubu_api 日志（P1 #16）。

    每次运行前清理旧 handler，避免跨进程 / 跨测试绑定到失效的 stderr
    （capsys 场景：每轮测试替换 sys.stderr，handler 必须重绑当前对象）。
    - 默认 WARNING：仅输出 warning / error
    - --verbose：DEBUG，输出请求级调试信息
    """
    for h in list(logger.handlers):
        logger.removeHandler(h)
    # 绑定当前 sys.stderr（capsys 生效时为捕获对象，确保测试可断言）
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="幕布 API 命令行工具")
    # P1 #16：--verbose 控制 debug 日志（默认仅 warning/error）
    parser.add_argument("--verbose", action="store_true",
                        help="输出调试日志（DEBUG 级别，含请求级信息）")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 登录（凭据取自环境变量 / ~/.workbuddy/.env.mubu；缺失时交互式输入，
    # 不再提供 --phone/--password 明文参数，避免出现在 ps / shell 历史中）
    login_parser = subparsers.add_parser(
        "login", help="登录幕布（凭据取自环境变量 / .env.mubu，缺失时交互式输入）"
    )

    # 列表
    list_parser = subparsers.add_parser("list", help="获取文档列表")
    list_parser.add_argument("--folder", default="0", help="文件夹ID")
    list_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # 创建文件夹
    folder_parser = subparsers.add_parser("mkdir", help="创建文件夹")
    folder_parser.add_argument("name", help="文件夹名称")
    folder_parser.add_argument("--parent", default="0", help="父文件夹ID")

    # 创建文档
    doc_parser = subparsers.add_parser("create", help="创建文档")
    doc_parser.add_argument("name", help="文档名称")
    doc_parser.add_argument("--folder", default="0", help="文件夹ID")
    doc_parser.add_argument("--content", default="", help="文档内容（大纲 JSON 字符串）")
    doc_parser.add_argument("--md", help="从 Markdown 文件导入内容")

    # 获取文档
    get_parser = subparsers.add_parser("get", help="获取文档内容")
    get_parser.add_argument("doc_id", help="文档ID")
    get_parser.add_argument("--export", choices=["markdown", "json"], default="json", help="导出格式")

    # 保存文档
    save_parser = subparsers.add_parser("save", help="保存文档")
    save_parser.add_argument("doc_id", help="文档ID")
    save_parser.add_argument("--file", help="从文件读取内容（原始大纲 JSON）")
    save_parser.add_argument("--md", help="从 Markdown 文件导入内容")
    save_parser.add_argument("--content", help="直接指定内容")

    # 删除
    delete_parser = subparsers.add_parser("delete", help="删除文档或文件夹")
    delete_parser.add_argument("id", help="文档或文件夹ID")
    delete_parser.add_argument("--type", choices=["doc", "folder"], default="folder",
                               help="对象类型：doc=文档 / folder=文件夹（默认 folder）")
    # Medium×3 修复：不可逆操作必须显式 --yes 才执行，否则 CLI 层中止。
    delete_parser.add_argument("--yes", action="store_true",
                               help="确认执行不可逆删除（必须显式传参）")

    # 移动
    move_parser = subparsers.add_parser("move", help="移动文档到其他文件夹")
    move_parser.add_argument("item_id", help="文档ID")
    move_parser.add_argument("--target", required=True, help="目标文件夹ID")

    # 搜索（T6，M4 T2 增加 --max-depth / --limit）
    search_parser = subparsers.add_parser("search", help="本地搜索文档/文件夹（按名称）")
    search_parser.add_argument("keyword", help="搜索关键字（大小写不敏感）")
    search_parser.add_argument("--max-depth", type=int, default=MAX_SEARCH_DEPTH,
                               help="递归深度上限（根 depth=0，默认 3 即最多展开 4 层）")
    search_parser.add_argument("--limit", type=int, default=MAX_SEARCH_LIMIT,
                               help="返回结果上限（默认 50）")
    search_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # 整树导出（Roadmap: 递归导出整个文件夹树为嵌套 Markdown）
    export_tree_parser = subparsers.add_parser(
        "export-tree", help="递归导出整个文件夹树为嵌套 Markdown 文件"
    )
    export_tree_parser.add_argument("--folder", default="0", help="根文件夹ID（默认根 0）")
    export_tree_parser.add_argument("--output", default=".", help="输出目录（默认当前目录）")
    export_tree_parser.add_argument("--max-depth", type=int, default=MAX_SEARCH_DEPTH,
                                    help="递归深度上限（默认 3）")

    # 重命名（Roadmap: 文档走 save_doc name；文件夹走推测端点 /list/update_folder）
    rename_parser = subparsers.add_parser("rename", help="重命名文档或文件夹")
    rename_parser.add_argument("id", help="文档或文件夹ID")
    rename_parser.add_argument("--name", required=True, help="新名称")
    rename_parser.add_argument("--type", choices=["doc", "folder"], default="doc",
                               help="对象类型：doc=走 save_doc name；folder=走推测端点 /list/update_folder")

    # OPML / FreeMind 导出（Roadmap: 兼容其它大纲工具）
    opml_parser = subparsers.add_parser("opml", help="将文档导出为 OPML / FreeMind XML")
    opml_parser.add_argument("doc_id", help="文档ID")
    opml_parser.add_argument("--format", choices=["opml", "freeplane"], default="opml",
                             help="导出格式（opml / freeplane）")

    args = parser.parse_args()
    _configure_logging(args.verbose)

    if not args.command:
        parser.print_help()
        return

    try:
        client = MubuClient()

        if args.command == "login":
            # 凭据优先来自环境变量 / .env.mubu；缺失时交互式输入
            # （无明文 CLI 参数，避免 ps / shell 历史泄露）
            if not client.phone:
                try:
                    client.phone = input("请输入幕布手机号: ").strip()
                except EOFError:
                    pass
            if not client.password:
                try:
                    client.password = getpass.getpass("请输入幕布密码: ")
                except EOFError:
                    pass
            result = client.login()
            print(f"登录成功: {result['username']} (ID: {result['user_id']})")

        elif args.command == "list":
            data = client.get_list(args.folder)
            if args.json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print(format_list(data))

        elif args.command == "mkdir":
            folder_id = client.create_folder(args.name, args.parent)
            print(f"创建文件夹成功: {folder_id}")

        elif args.command == "create":
            md_path = getattr(args, "md", None)
            if md_path:
                safe = _safe_local_path(md_path)
                # create_doc 的 content 同样是 definition JSON 字符串 {"nodes":[...]}，
                # 与 get_doc 返回的 nodes 同构；markdown_to_doc 返回 {"node":{...}}，
                # 此处取其根节点包成单顶层节点的 definition。
                md_doc = markdown_to_doc(safe.read_text(encoding="utf-8"))
                content = json.dumps({"nodes": [md_doc.get("node")]}, ensure_ascii=False)
            else:
                content = args.content
            doc_id = client.create_doc(args.name, args.folder, content)
            print(f"创建文档成功: {doc_id}")

        elif args.command == "get":
            doc = client.get_doc(args.doc_id)
            if args.export == "json":
                print(json.dumps(doc, indent=2, ensure_ascii=False))
            else:
                print(export_markdown(doc))

        elif args.command == "save":
            md_path = getattr(args, "md", None)
            file_path = args.file
            if md_path:
                safe = _safe_local_path(md_path)
                # save_doc 的 content 必须是 definition JSON 字符串 {"nodes":[...]}，
                # 与 get_doc 返回的 nodes 同构；markdown_to_doc 返回 {"node":{...}}，
                # 此处取其根节点包成单顶层节点的 definition。
                md_doc = markdown_to_doc(safe.read_text(encoding="utf-8"))
                content = json.dumps({"nodes": [md_doc.get("node")]}, ensure_ascii=False)
            elif file_path:
                safe = _safe_local_path(file_path)
                content = safe.read_text(encoding="utf-8")
            elif args.content:
                content = args.content
            else:
                content = sys.stdin.read()
            client.save_doc(args.doc_id, content)
            print("保存成功")

        elif args.command == "delete":
            # Medium×3 修复：delete 为不可逆操作，CLI 层守卫。
            # 未显式传 --yes 时，打印不可逆警示并 sys.exit(1) 中止，
            # 绝不调用 client.delete(...)；仅当 args.yes 为真才执行删除。
            if not args.yes:
                logger.warning(
                    "删除不可逆：即将删除幕布%s %s。确认请加 --yes 重新执行。",
                    "文档" if args.type == "doc" else "文件夹", args.id,
                )
                sys.exit(1)
            client.delete(args.id, args.type)
            print("删除成功")

        elif args.command == "move":
            client.move(args.item_id, args.target)
            print(f"移动成功: {args.item_id} -> {args.target}")

        elif args.command == "search":
            result = client.search(
                args.keyword,
                max_depth=args.max_depth,
                limit=args.limit,
            )
            results = result["results"]
            # 结果因达到上限被截断时，提示调用方结果可能不完整
            if result.get("truncated"):
                logger.warning(
                    "搜索因达到上限（limit=%s）而提前结束，结果可能不完整",
                    result.get("limit"),
                )
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                print(format_search(results))

        elif args.command == "export-tree":
            stats = client.export_tree(
                args.folder, args.output, max_depth=args.max_depth
            )
            summary = f"导出完成: {stats['docs']} 文档 / {stats['folders']} 文件夹"
            if stats["errors"]:
                summary += f"（{stats['errors']} 失败）"
            print(summary)

        elif args.command == "rename":
            if args.type == "doc":
                client.rename_doc(args.id, args.name)
            else:
                # 文件夹重命名走逆向推测端点，真实环境需验证
                client.rename_folder(args.id, args.name)
            print(f"重命名成功: {args.id} -> {args.name}")

        elif args.command == "opml":
            doc = client.get_doc(args.doc_id)
            if args.format == "freeplane":
                print(doc_to_freeplane(doc))
            else:
                print(doc_to_opml(doc))

    except Exception as e:
        # 仅记录 msg（已脱敏：不含密码/token/原始 body），不泄露敏感信息
        logger.error("%s", e)
        sys.exit(1)
