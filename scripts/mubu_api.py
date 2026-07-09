#!/usr/bin/env python3
"""
幕布 API 封装脚本
支持登录、文档管理、文件夹操作、Markdown 导入导出等功能。

M1（P0）阶段新增能力：
- Markdown 导出：doc_to_markdown / export_markdown
- Markdown 导入：markdown_to_doc
- move 子命令
- Token 刷新 + 401 仅重试 1 次（杜绝死循环）

M2（P1）阶段新增能力（本期实现 T5 + T6）：
- T5 网络健壮性：_request 增加 timeout=15、非 JSON 响应友好异常、网络层/5xx
  指数退避重试（最多 2 次，与 401 重登重试清晰分层、互不干扰）
- T5 .env 凭据加载：_load_env_file() 读取 ~/.workbuddy/.env.mubu（仅环境变量未设置时补全）
- T5 Token 文件权限 600（_save_token 原子写后 chmod）
- T6 本地搜索：search() 从根文件夹递归遍历，按名称本地过滤（mubu 无公开搜索端点）
- CLI 新增 search 子命令
"""

import os
import re
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

# API 基础配置
BASE_URL = "https://api2.mubu.com/v3/api"
TOKEN_FILE = Path.home() / ".mubu_token"

# .env 凭据文件路径：仅当环境变量未设置时用于补全 MUBU_PHONE / MUBU_PASSWORD
ENV_FILE = Path.home() / ".workbuddy" / ".env.mubu"

# 默认请求头
DEFAULT_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://mubu.com",
    "Referer": "https://mubu.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 接口路径常量：统一在此维护，便于后续集中修改
ENDPOINTS = {
    "login": "/user/phone_login",
    "list": "/list/get",
    "create_folder": "/list/create_folder",
    "create_doc": "/list/create_doc",
    "get_doc": "/doc/get",
    "save_doc": "/doc/save",
    "delete": "/list/delete",
    "move": "/list/move",
}

# 网络重试配置（T5）
# 单次请求超时（秒）
REQUEST_TIMEOUT = 15
# 网络层/5xx 最大重试次数（不含首次，即最多共发起 3 次请求）
MAX_NETWORK_RETRIES = 2
# 指数退避时间（秒）：第 1 次重试等 1s，第 2 次等 2s
NETWORK_BACKOFF = (1, 2)
# Token 文件权限：仅属主可读写
TOKEN_FILE_MODE = 0o600
# 异常 body 截断长度，避免超大响应体污染错误信息
BODY_TRUNCATE = 200


class MubuError(Exception):
    """幕布 API 基础异常。

    M1 阶段定义基础结构（msg / status_code / body）。
    M2 的 T5 在其基础上增强：body 自动截断前 BODY_TRUNCATE 字，
    避免超大响应体（如限流 HTML 页面）撑爆错误信息。
    请勿在此重复定义完整字段以外的内容。
    """

    def __init__(self, msg: str, status_code: Optional[int] = None, body: Any = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.status_code = status_code
        # body 若为字符串则截断，避免非 JSON / 错误页面撑爆异常信息
        if isinstance(body, str) and len(body) > BODY_TRUNCATE:
            body = body[:BODY_TRUNCATE]
        self.body = body


class MubuClient:
    """幕布 API 客户端"""

    def __init__(self, phone: Optional[str] = None, password: Optional[str] = None) -> None:
        # T5：在读取 phone/password 之前，先尝试从 .env 文件补全凭据
        self._load_env_file()
        self.phone = phone or os.getenv("MUBU_PHONE")
        self.password = password or os.getenv("MUBU_PASSWORD")
        self.token = None
        self.user_id = None
        self.username = None
        self.expires_at = 0  # Token 过期时间戳（秒）
        self._load_token()

    def _load_env_file(self, path: Optional[Path] = None) -> None:
        """从 .env 文件加载凭据（仅当环境变量未设置时补全）。

        默认读取 ENV_FILE（~/.workbuddy/.env.mubu）；文件不存在则静默跳过。
        逐行解析 KEY=VALUE，忽略空行与 # 注释行。
        仅补全 MUBU_PHONE / MUBU_PASSWORD，且环境变量已设置时优先于文件。

        Args:
            path: 可选，指定 .env 文件路径（便于测试；默认用 ENV_FILE）
        """
        env_path = path or ENV_FILE
        if not env_path.exists():
            return
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # 仅在环境变量未设置时补全
                if key in ("MUBU_PHONE", "MUBU_PASSWORD") and not os.getenv(key):
                    os.environ[key] = value
        except Exception:
            # 加载失败不影响主流程，后续 login 会提示设置环境变量
            pass

    def _load_token(self) -> bool:
        """从本地加载 Token（未过期才生效）"""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                expires_at = data.get("expires_at", 0)
                if time.time() < expires_at:
                    self.token = data.get("token")
                    self.user_id = data.get("user_id")
                    self.username = data.get("username")
                    self.expires_at = expires_at
                    return True
            except Exception:
                pass
        return False

    def _save_token(self) -> None:
        """原子写 Token 到本地：先写临时文件再 rename，避免中途崩溃留残缺文件。

        T5：rename 之后追加 chmod 0o600，确保 Token 文件仅属主可读写。
        """
        self.expires_at = time.time() + 7200  # 2 小时过期
        data = {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username,
            "expires_at": self.expires_at
        }
        tmp = TOKEN_FILE.parent / (TOKEN_FILE.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.rename(tmp, TOKEN_FILE)
        # T5：设置权限 600，防止其它用户读取 Token
        os.chmod(TOKEN_FILE, TOKEN_FILE_MODE)

    def _get_headers(self) -> Dict[str, str]:
        """获取带认证的请求头"""
        headers = DEFAULT_HEADERS.copy()
        if self.token:
            headers["jwt-token"] = self.token
        return headers

    def ensure_valid_token(self) -> None:
        """确保 Token 有效，临近过期则重新登录。

        刷新策略：未持有 token，或距过期不足 (300 + leeway) 秒时重新登录。
        leeway=60 预留网络与处理余量。不依赖 refresh_token，凭据来自缓存的
        phone/password。
        """
        leeway = 60
        if not self.token or time.time() > self.expires_at - 300 - leeway:
            self.login()

    def _is_auth_error(self, result: Dict[str, Any], response: "requests.Response") -> bool:
        """判断是否为鉴权失效错误。

        仅当 HTTP 401，或响应 code 表示登录失效（含相关关键字）时返回 True。
        403 权限不足或其它非 0 code 不触发重登，避免误重试。
        """
        if response.status_code == 401:
            return True
        code = result.get("code")
        if code is not None and code != 0:
            msg = str(result.get("msg", "")).lower()
            auth_keywords = (
                "登录", "login", "token", "未登录", "过期",
                "expire", "auth", "unauthorized", "重新登录"
            )
            if any(k in msg for k in auth_keywords):
                return True
        return False

    def _http_request(self, method: str, url: str, headers: Dict[str, str],
                      **kwargs) -> requests.Response:
        """执行一次 HTTP 请求，对网络层异常与 5xx 进行指数退避重试。

        此层只负责网络健壮性，**不触发重登**：
        - requests.exceptions.RequestException（超时/连接错误/网络抖动）→ 重试
        - HTTP 5xx（服务端错误）→ 重试
        重试上限 MAX_NETWORK_RETRIES（即最多共发起 3 次请求），退避见 NETWORK_BACKOFF。
        4xx（含 401）等非 5xx 响应会原样返回，交由上层 _request 处理鉴权重试。
        """
        last_err: Optional[Exception] = None
        for attempt in range(MAX_NETWORK_RETRIES + 1):
            try:
                response = requests.request(
                    method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
                )
            except requests.exceptions.RequestException as e:
                # 网络层异常：退避后重试
                last_err = e
                if attempt < MAX_NETWORK_RETRIES:
                    time.sleep(NETWORK_BACKOFF[min(attempt, len(NETWORK_BACKOFF) - 1)])
                    continue
                raise MubuError(
                    f"网络请求失败（已重试 {MAX_NETWORK_RETRIES} 次）: {e}",
                    status_code=None,
                )

            # 5xx 服务端错误 → 退避重试（不重登）
            if response.status_code >= 500:
                last_err = None
                if attempt < MAX_NETWORK_RETRIES:
                    time.sleep(NETWORK_BACKOFF[min(attempt, len(NETWORK_BACKOFF) - 1)])
                    continue
                raise MubuError(
                    f"服务端错误（HTTP {response.status_code}），已重试 "
                    f"{MAX_NETWORK_RETRIES} 次仍失败",
                    status_code=response.status_code,
                    body=response.text,
                )

            # 非 5xx（含 401 等 4xx、2xx）原样返回，交由上层处理
            return response

        # 理论不可达：兜底抛错，避免漏掉 last_err
        raise MubuError(
            f"网络请求失败（已耗尽重试）: {last_err}",
            status_code=None,
        )

    def _request(self, method: str, endpoint: str, max_retries: int = 1,
                 auth: bool = True, **kwargs: Any) -> Dict:
        """发送 HTTP 请求，统一处理鉴权与重试。

        分层说明（T5 增强）：
        - 网络层/5xx 重试：由 _http_request 负责，最多 2 次，不重登。
        - 鉴权失效重试：本方法递归处理，max_retries 默认 1（仅重试 1 次，杜绝死循环）。

        两条链路互斥、互不干扰：网络重试只重发请求，鉴权重试才重登。

        Args:
            method: HTTP 方法
            endpoint: 接口路径（取自 ENDPOINTS）
            max_retries: 鉴权失败时的重试次数上限（默认 1，杜绝死循环）
            auth: 是否需要在发起前确保 Token 有效（login 自身应传 False）
        """
        if auth:
            self.ensure_valid_token()

        url = f"{BASE_URL}{endpoint}"
        headers = self._get_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        # 网络层/5xx 重试在 _http_request 内完成，这里拿到的是已确认非 5xx 的响应
        response = self._http_request(method, url, headers, **kwargs)

        # 响应体非 JSON（限流 HTML / 502 错误页等）→ 抛友好异常，不再抛裸 JSONDecodeError
        try:
            result = response.json()
        except ValueError:
            raise MubuError(
                f"响应解析失败（status={response.status_code}, url={url}）："
                f"响应体不是预期的 JSON",
                status_code=response.status_code,
                body=response.text,
            )

        # 仅鉴权失效才重登重试；第二次仍失败则抛错，不再重登
        if self._is_auth_error(result, response):
            if max_retries > 0:
                self.login()
                return self._request(method, endpoint, max_retries=max_retries - 1, auth=auth, **kwargs)
            raise MubuError(
                f"鉴权失败且重试后仍失败: {result.get('msg', '未知错误')}",
                status_code=response.status_code,
                body=result,
            )

        if result.get("code") != 0:
            # 403 权限不足或其它业务错误，不触发重登
            raise MubuError(
                f"API 错误: {result.get('msg', '未知错误')}",
                status_code=response.status_code,
                body=result,
            )

        return result.get("data", {})

    def login(self) -> Dict:
        """登录幕布（auth 引导，自身不走 ensure_valid_token）"""
        if not self.phone or not self.password:
            raise MubuError("请设置 MUBU_PHONE 和 MUBU_PASSWORD 环境变量，或传入参数")

        data = self._request("POST", ENDPOINTS["login"], auth=False, max_retries=0, json={
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

    def ensure_login(self) -> None:
        """确保已登录（兼容旧调用；_request 内已统一处理）"""
        if not self.token:
            self.login()

    def get_list(self, folder_id: str = "0") -> List[Dict]:
        """获取文件夹下的文档和子文件夹列表"""
        self.ensure_login()
        data = self._request("POST", ENDPOINTS["list"], json={"folderId": folder_id})
        return data

    def create_folder(self, name: str, parent_id: str = "0") -> str:
        """创建文件夹"""
        self.ensure_login()
        data = self._request("POST", ENDPOINTS["create_folder"], json={
            "folderId": parent_id,
            "name": name
        })
        return data.get("folder", {}).get("id", "")

    def create_doc(self, name: str, folder_id: str = "0", content: str = "") -> str:
        """创建文档"""
        self.ensure_login()
        data = self._request("POST", ENDPOINTS["create_doc"], json={
            "folderId": folder_id,
            "name": name,
            "content": content
        })
        return data.get("doc", {}).get("id", "")

    def get_doc(self, doc_id: str) -> Dict:
        """获取文档内容"""
        self.ensure_login()
        return self._request("POST", ENDPOINTS["get_doc"], json={"id": doc_id})

    def save_doc(self, doc_id: str, content: str, name: Optional[str] = None) -> None:
        """保存文档"""
        self.ensure_login()
        data = {"id": doc_id, "content": content}
        if name:
            data["name"] = name
        self._request("POST", ENDPOINTS["save_doc"], json=data)

    def delete(self, item_id: str) -> None:
        """删除文档或文件夹"""
        self.ensure_login()
        self._request("POST", ENDPOINTS["delete"], json={"id": item_id})

    def move(self, item_id: str, target_folder_id: str) -> None:
        """移动文档到其他文件夹"""
        self.ensure_login()
        self._request("POST", ENDPOINTS["move"], json={
            "id": item_id,
            "folderId": target_folder_id
        })

    def search(self, keyword: str, root_folder_id: str = "0") -> List[Dict]:
        """本地递归搜索：名称包含关键字的文档与文件夹（T6）。

        mubu 无公开 /search 端点，本期采用本地过滤：从根文件夹开始递归遍历
        所有子文件夹，收集 name 包含 keyword（大小写不敏感）的条目。

        Args:
            keyword: 搜索关键字（大小写不敏感）
            root_folder_id: 遍历起点文件夹 ID，默认 "0"（根）

        Returns:
            匹配项列表，每项含 id / name / type（"doc" | "folder"）/ path（从根起的路径）
        """
        keyword_lower = (keyword or "").lower()
        results: List[Dict] = []

        def walk(folder_id: str, path: str) -> None:
            """递归遍历 folder_id，将命中项追加到 results。"""
            try:
                data = self.get_list(folder_id)
            except MubuError as e:
                # 单个文件夹拉取失败不阻断整体遍历
                print(f"警告: 遍历文件夹 {folder_id} 失败: {e}", file=sys.stderr)
                return

            folders = data.get("folders", []) or []
            docs = data.get("docs", []) or []

            # 文档匹配
            for d in docs:
                name = d.get("name", "")
                if keyword_lower and keyword_lower in name.lower():
                    results.append({
                        "id": d.get("id"),
                        "name": name,
                        "type": "doc",
                        "path": path,
                    })

            # 文件夹匹配 + 递归子文件夹
            for f in folders:
                name = f.get("name", "")
                if keyword_lower and keyword_lower in name.lower():
                    results.append({
                        "id": f.get("id"),
                        "name": name,
                        "type": "folder",
                        "path": path,
                    })
                # 递归进入子文件夹，路径追加当前文件夹名
                child_path = f"{path}/{name}" if path else name
                walk(f.get("id"), child_path)

        walk(root_folder_id, "")
        return results


def doc_to_markdown(node: Dict[str, Any], level: int = 0) -> str:
    """将节点（及其子树）递归渲染为 Markdown 列表片段。

    子节点使用 '- ' 列表项，缩进 = 2 * level；含 checked 渲染为 '- [x]'/'- [ ]'；
    含 note 在其子树之后追加 '> {note}'。根标题（'# '）由 export_markdown 负责。

    Args:
        node: 节点字典，可包含 text / checked / note / children
        level: 当前节点深度（根节点的直接子节点为 0）

    Returns:
        Markdown 列表片段（不含根标题行）
    """
    lines: List[str] = []
    text = (node.get("text") or "").replace("\n", " ")
    indent = " " * (2 * level)

    # 勾选状态（mark 为单个字符 x / 空格）
    if node.get("checked") is not None:
        mark = "x" if node.get("checked") else " "
        lines.append(f"{indent}- [{mark}] {text}")
    else:
        lines.append(f"{indent}- {text}")

    # 递归子节点（位于 note 之前）
    for child in node.get("children") or []:
        lines.append(doc_to_markdown(child, level + 1))

    # 备注：节点（含其子树）之后追加
    note = node.get("note")
    if note:
        lines.append(f"{indent}> {note}")

    return "\n".join(lines)


def export_markdown(doc: Dict[str, Any]) -> str:
    """将文档 data 层转换为 Markdown 文本。

    Args:
        doc: get_doc() 返回的 data 层，结构 {"node": {"text":..., "children":[...]}}

    Returns:
        Markdown 文本（首行为 '# 标题'）

    Raises:
        MubuError: 文档结构无效（既无有效 text 也无 children）时
    """
    root = doc.get("node") or doc
    if not isinstance(root, dict) or (not root.get("text") and not root.get("children")):
        raise MubuError("无效的文档结构")

    title = (root.get("text") or "").replace("\n", " ")
    lines = [f"# {title}"]
    for child in root.get("children") or []:
        lines.append(doc_to_markdown(child, level=0))
    return "\n".join(lines)


def markdown_to_doc(md: str) -> Dict[str, Any]:
    r"""将 Markdown 文本解析为幕布文档结构。

    解析规则（按行）：
    - 标题 '^#+\s+(.*)' → 顶层节点；多个顶层标题时第一个为 root，其余作为 root 的 children
    - 无序列表 '^(\s*)-\s+(.*)' → 子节点；前导空格数 // 2 = 相对深度，用栈维护 (depth → node)
    - 勾选 '- [ ]'/'- [x]' → 设 checked
    - 引用 '^(\s*)>\s+(.*)' → 作为上一层级节点的 note（按缩进深度归属）
    - 纯文本无列表 → 整个作为单节点正文

    Returns:
        {"node": {"id": "root", "text": ..., "children": [...]}}
    """
    root_node: Dict[str, Any] = {"id": "root", "text": "", "children": []}
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"node_{counter[0]}"

    lines = md.split("\n")

    # 收集所有标题行
    headings: List[str] = []
    for line in lines:
        if not line.strip():
            continue
        m = re.match(r"^#+\s+(.*)$", line)
        if m:
            headings.append(m.group(1).strip())

    # 是否存在列表项
    has_list = any(
        re.match(r"^\s*-\s+", line) for line in lines if line.strip()
    )

    # 纯文本（无标题且无列表）
    if not headings and not has_list:
        text = md.strip()
        if text:
            root_node["text"] = text
        return {"node": root_node}

    # 设置 root 文本，其余标题作为 root 的 children
    if headings:
        root_node["text"] = headings[0]
        for h in headings[1:]:
            root_node["children"].append({"id": next_id(), "text": h, "children": []})

    if not has_list:
        return {"node": root_node}

    # 用栈维护 (depth, node)；栈底为 root
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root_node)]

    for line in lines:
        if not line.strip():
            continue

        # 标题行已处理（root 文本 / children），跳过
        if re.match(r"^#+\s+", line):
            continue

        # 引用 → 作为对应层级节点的 note
        m_note = re.match(r"^(\s*)>\s+(.*)$", line)
        if m_note:
            note_depth = len(m_note.group(1)) // 2
            note_text = m_note.group(2).strip()
            target = root_node
            for d, n in reversed(stack):
                if d == note_depth:
                    target = n
                    break
            target["note"] = note_text
            continue

        # 无序列表项
        m_list = re.match(r"^(\s*)-\s+(.*)$", line)
        if m_list:
            indent = len(m_list.group(1))
            depth = indent // 2
            content = m_list.group(2).strip()

            # 勾选状态
            checked: Optional[bool] = None
            mc = re.match(r"^\[([ xX])\]\s+(.*)$", content)
            if mc:
                checked = mc.group(1).lower() == "x"
                content = mc.group(2).strip()

            node: Dict[str, Any] = {"id": next_id(), "text": content, "children": []}
            if checked is not None:
                node["checked"] = checked

            # 弹出比当前深度更深或相等的节点，找到父节点
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent = stack[-1][1] if stack else root_node
            parent.setdefault("children", []).append(node)
            stack.append((depth, node))
            continue

    return {"node": root_node}


def format_list(data: Dict) -> str:
    """格式化文档列表为可读文本。

    T5：仅使用 docs 键（data.get("docs")），与 get_list 返回结构对齐，
    移除对 documents 键的兜底。
    """
    lines = []
    folders = data.get("folders", [])
    docs = data.get("docs", [])

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


def format_search(results: List[Dict]) -> str:
    """格式化搜索结果为可读文本，复用 format_list 的分区展示风格（T6）。

    将匹配项分为 📁 文件夹 / 📄 文档 两区，命中项附带路径（path）便于定位。
    """
    folders = [r for r in results if r.get("type") == "folder"]
    docs = [r for r in results if r.get("type") == "doc"]
    lines = []

    if folders:
        lines.append("📁 文件夹:")
        for f in folders:
            path = f.get("path", "")
            suffix = f"  ({path})" if path else ""
            lines.append(f"  [{f.get('id')}] {f.get('name')}{suffix}")

    if docs:
        lines.append("\n📄 文档:")
        for d in docs:
            path = d.get("path", "")
            suffix = f"  ({path})" if path else ""
            lines.append(f"  [{d.get('id')}] {d.get('name')}{suffix}")

    if not folders and not docs:
        lines.append("（无匹配结果）")

    return "\n".join(lines)


def main() -> None:
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

    # 移动
    move_parser = subparsers.add_parser("move", help="移动文档到其他文件夹")
    move_parser.add_argument("item_id", help="文档ID")
    move_parser.add_argument("--target", required=True, help="目标文件夹ID")

    # 搜索（T6）
    search_parser = subparsers.add_parser("search", help="本地搜索文档/文件夹（按名称）")
    search_parser.add_argument("keyword", help="搜索关键字（大小写不敏感）")
    search_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

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
            if getattr(args, "md", None):
                content = json.dumps(markdown_to_doc(Path(args.md).read_text(encoding="utf-8")), ensure_ascii=False)
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
            if getattr(args, "md", None):
                content = json.dumps(markdown_to_doc(Path(args.md).read_text(encoding="utf-8")), ensure_ascii=False)
            elif args.file:
                content = Path(args.file).read_text(encoding="utf-8")
            elif args.content:
                content = args.content
            else:
                content = sys.stdin.read()
            client.save_doc(args.doc_id, content)
            print("保存成功")

        elif args.command == "delete":
            client.delete(args.id)
            print("删除成功")

        elif args.command == "move":
            client.move(args.item_id, args.target)
            print(f"移动成功: {args.item_id} -> {args.target}")

        elif args.command == "search":
            results = client.search(args.keyword)
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                print(format_search(results))

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
