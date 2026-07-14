#!/usr/bin/env python3
"""幕布 API 封装脚本 — 向后兼容 shim。

历史的调用方式仍然有效：
- ``import mubu_api`` 及其公开符号（MubuClient / MubuError / doc_to_markdown / ...）
- ``python scripts/mubu_api.py <subcommand>``

实际逻辑已迁移至 ``scripts/mubu/`` 包（config / convert / client / cli），
本文件仅做重新导出，不重复实现，避免逻辑分叉。

为保持对旧调用方与既有测试的最大兼容，本 shim 同时重新导出原单文件版本中
存在的模块级标准库名称（os / sys / json / time / re / logging / getpass /
argparse / requests / Path / ...），使 ``mubu_api.os``、``mubu_api.getpass``
等引用依旧可用（os / getpass 为单例模块，monkeypatch 行为保持一致）。

模块化拆分里程碑：v1.3.0（非 breaking）。

能力一览：
- 登录 / 列表 / 文件夹 / 文档 / 删除 / 移动
- Markdown 导入导出（doc_to_markdown / export_markdown / markdown_to_doc）
- 本地递归搜索（search）
- 整树导出（export_tree）
- 重命名（rename_doc 走 save_doc name；rename_folder 走逆向推测端点 /list/update_folder）
- OPML / FreeMind 导出（doc_to_opml / doc_to_freeplane）
"""

# 标准库（作为模块级属性重新导出，保持向后兼容）
import os
import sys
import json
import time
import re
import logging
import getpass
import argparse
import requests
import fcntl
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlparse
from typing import Optional, Dict, List, Any, Tuple, Iterator

# 包内模块符号
from mubu.config import (
    logger,
    DEFAULT_BASE_URL,
    ALLOWED_BASE_HOSTS,
    _resolve_base_url,
    BASE_URL,
    TOKEN_FILE,
    ENV_FILE,
    DEFAULT_HEADERS,
    ENDPOINTS,
    REQUEST_TIMEOUT,
    MAX_NETWORK_RETRIES,
    NETWORK_BACKOFF,
    TOKEN_FILE_MODE,
    BODY_TRUNCATE,
    MAX_SEARCH_DEPTH,
    MAX_SEARCH_LIMIT,
    MAX_SEARCH_REQUESTS,
    _token_file_lock,
    MubuError,
    _safe_local_path,
)
from mubu.convert import (
    doc_to_markdown,
    export_markdown,
    _safe_filename,
    doc_to_opml,
    doc_to_freeplane,
    markdown_to_doc,
    format_list,
    format_search,
)
from mubu.client import MubuClient
from mubu.cli import main, _configure_logging

__all__ = [
    # 标准库（兼容旧引用）
    "os",
    "sys",
    "json",
    "time",
    "re",
    "logging",
    "getpass",
    "argparse",
    "requests",
    "fcntl",
    "Path",
    "contextmanager",
    "urlparse",
    "Optional",
    "Dict",
    "List",
    "Any",
    "Tuple",
    "Iterator",
    # config
    "logger",
    "DEFAULT_BASE_URL",
    "ALLOWED_BASE_HOSTS",
    "_resolve_base_url",
    "BASE_URL",
    "TOKEN_FILE",
    "ENV_FILE",
    "DEFAULT_HEADERS",
    "ENDPOINTS",
    "REQUEST_TIMEOUT",
    "MAX_NETWORK_RETRIES",
    "NETWORK_BACKOFF",
    "TOKEN_FILE_MODE",
    "BODY_TRUNCATE",
    "MAX_SEARCH_DEPTH",
    "MAX_SEARCH_LIMIT",
    "MAX_SEARCH_REQUESTS",
    "_token_file_lock",
    "MubuError",
    "_safe_local_path",
    # convert
    "doc_to_markdown",
    "export_markdown",
    "_safe_filename",
    "doc_to_opml",
    "doc_to_freeplane",
    "markdown_to_doc",
    "format_list",
    "format_search",
    # client
    "MubuClient",
    # cli
    "main",
    "_configure_logging",
]

if __name__ == "__main__":
    main()
