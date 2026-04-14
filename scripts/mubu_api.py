#!/usr/bin/env python3
"""
幕布 API 封装脚本
支持登录、文档管理、文件夹操作等功能
"""

import os
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any

# API 基础配置
BASE_URL = "https://api2.mubu.com/v3/api"
TOKEN_FILE = Path.home() / ".mubu_token"

# 默认请求头
DEFAULT_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://mubu.com",
    "Referer": "https://mubu.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


class MubuClient:
    """幕布 API 客户端"""

    def __init__(self, phone: str = None, password: str = None):
        self.phone = phone or os.getenv("MUBU_PHONE")
        self.password = password or os.getenv("MUBU_PASSWORD")
        self.token = None
        self.user_id = None
        self.username = None
        self._load_token()

    def _load_token(self):
        """从本地加载 Token"""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                if time.time() < data.get("expires_at", 0):
                    self.token = data.get("token")
                    self.user_id = data.get("user_id")
                    self.username = data.get("username")
                    return True
            except Exception:
                pass
        return False

    def _save_token(self):
        """保存 Token 到本地"""
        data = {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username,
            "expires_at": time.time() + 7200  # 2小时
        }
        TOKEN_FILE.write_text(json.dumps(data, indent=2))

    def _get_headers(self) -> Dict[str, str]:
        """获取带认证的请求头"""
        headers = DEFAULT_HEADERS.copy()
        if self.token:
            headers["jwt-token"] = self.token
        return headers

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """发送请求"""
        url = f"{BASE_URL}{endpoint}"
        headers = self._get_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        response = requests.request(method, url, headers=headers, **kwargs)
        result = response.json()

        if result.get("code") != 0:
            raise Exception(f"API 错误: {result.get('msg', '未知错误')}")

        return result.get("data", {})

    def login(self) -> Dict:
        """登录幕布"""
        if not self.phone or not self.password:
            raise Exception("请设置 MUBU_PHONE 和 MUBU_PASSWORD 环境变量，或传入参数")

        data = self._request("POST", "/user/phone_login", json={
            "phone": self.phone,
            "password": self.password,
            "callbackType": 0
        })

        # 登录返回的是扁平结构，token 和用户信息都在 data 里
        self.token = data["token"]
        self.user_id = data["id"]
        self.username = data["name"]
        self._save_token()

        return {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username
        }

    def ensure_login(self):
        """确保已登录"""
        if not self.token:
            self.login()

    def get_list(self, folder_id: str = "0") -> List[Dict]:
        """获取文件夹下的文档和子文件夹列表"""
        self.ensure_login()
        data = self._request("POST", "/list/get", json={"folderId": folder_id})
        return data

    def create_folder(self, name: str, parent_id: str = "0") -> str:
        """创建文件夹"""
        self.ensure_login()
        data = self._request("POST", "/list/create_folder", json={
            "folderId": parent_id,
            "name": name
        })
        return data.get("folder", {}).get("id", "")

    def create_doc(self, name: str, folder_id: str = "0", content: str = "") -> str:
        """创建文档"""
        self.ensure_login()
        data = self._request("POST", "/list/create_doc", json={
            "folderId": folder_id,
            "name": name,
            "content": content
        })
        return data.get("doc", {}).get("id", "")

    def get_doc(self, doc_id: str) -> Dict:
        """获取文档内容"""
        self.ensure_login()
        return self._request("POST", "/doc/get", json={"id": doc_id})

    def save_doc(self, doc_id: str, content: str, name: str = None):
        """保存文档"""
        self.ensure_login()
        data = {"id": doc_id, "content": content}
        if name:
            data["name"] = name
        self._request("POST", "/doc/save", json=data)

    def delete(self, item_id: str):
        """删除文档或文件夹"""
        self.ensure_login()
        self._request("POST", "/list/delete", json={"id": item_id})

    def move(self, item_id: str, target_folder_id: str):
        """移动文档到其他文件夹"""
        self.ensure_login()
        self._request("POST", "/list/move", json={
            "id": item_id,
            "folderId": target_folder_id
        })


def format_list(data: Dict) -> str:
    """格式化文档列表为可读文本"""
    lines = []
    folders = data.get("folders", [])
    docs = data.get("docs", []) or data.get("documents", [])

    if folders:
        lines.append("📁 文件夹:")
        for f in folders:
            name = f.get("name", "未命名")
            fid = f.get("id", "")
            lines.append(f"  [{fid}] {name}")

    if docs:
        lines.append("\n📄 文档:")
        for d in docs:
            name = d.get("name", "未命名")
            did = d.get("id", "")
            lines.append(f"  [{did}] {name}")

    if not folders and not docs:
        lines.append("（空）")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="幕布 API 命令行工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 登录
    login_parser = subparsers.add_parser("login", help="登录幕布")
    login_parser.add_argument("--phone", help="手机号")
    login_parser.add_argument("--password", help="密码")

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
    doc_parser.add_argument("--content", default="", help="文档内容")

    # 获取文档
    get_parser = subparsers.add_parser("get", help="获取文档内容")
    get_parser.add_argument("doc_id", help="文档ID")
    get_parser.add_argument("--export", choices=["markdown", "json"], default="json", help="导出格式")

    # 保存文档
    save_parser = subparsers.add_parser("save", help="保存文档")
    save_parser.add_argument("doc_id", help="文档ID")
    save_parser.add_argument("--file", help="从文件读取内容")
    save_parser.add_argument("--content", help="直接指定内容")

    # 删除
    delete_parser = subparsers.add_parser("delete", help="删除文档或文件夹")
    delete_parser.add_argument("id", help="文档或文件夹ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        client = MubuClient(
            phone=getattr(args, "phone", None),
            password=getattr(args, "password", None)
        )

        if args.command == "login":
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
            doc_id = client.create_doc(args.name, args.folder, args.content)
            print(f"创建文档成功: {doc_id}")

        elif args.command == "get":
            doc = client.get_doc(args.doc_id)
            if args.export == "json":
                print(json.dumps(doc, indent=2, ensure_ascii=False))
            else:
                print("（Markdown 导出暂不可用，请使用 --export json）")

        elif args.command == "save":
            if args.file:
                content = Path(args.file).read_text()
            elif args.content:
                content = args.content
            else:
                content = sys.stdin.read()
            client.save_doc(args.doc_id, content)
            print("保存成功")

        elif args.command == "delete":
            client.delete(args.id)
            print("删除成功")

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
