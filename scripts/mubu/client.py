"""mubu 包 — MubuClient：鉴权、请求、文档/文件夹/搜索/导出等操作。"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Iterator

import requests

from mubu.config import (
    logger,
    BASE_URL,
    DEFAULT_HEADERS,
    ENDPOINTS,
    ENV_FILE,
    TOKEN_FILE,
    REQUEST_TIMEOUT,
    MAX_NETWORK_RETRIES,
    NETWORK_BACKOFF,
    TOKEN_FILE_MODE,
    _token_file_lock,
    MubuError,
    MAX_SEARCH_DEPTH,
    MAX_SEARCH_LIMIT,
    MAX_SEARCH_REQUESTS,
)
from mubu.convert import (
    export_markdown,
    _safe_filename,
)


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
        # P2 #22：复用 requests.Session 连接池，search 多请求场景下避免每次新建连接
        self._session = requests.Session()
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
        # 安全官 #1：凭据文件仅属主可读写，加载时强制 600（失败不影响加载）
        try:
            os.chmod(env_path, 0o600)
        except Exception:
            pass
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

        M2 的 T5：rename 之后追加 chmod 0o600，确保 Token 文件仅属主可读写。
        M4 的 T3：原子写整体用跨进程文件锁包裹，避免多进程并发写损坏 Token 文件。
        """
        self.expires_at = time.time() + 7200  # 2 小时过期
        data = {
            "token": self.token,
            "user_id": self.user_id,
            "username": self.username,
            "expires_at": self.expires_at
        }
        with _token_file_lock():
            tmp = TOKEN_FILE.parent / (TOKEN_FILE.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.rename(tmp, TOKEN_FILE)
            # M2 的 T5：设置权限 600，防止其它用户读取 Token
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
            # 收紧关键字：仅保留明确指向登录失效的短语，移除 "token"/"auth"/
            # "expire"/"login"/"过期" 等易出现在正常业务错误中的泛化词，
            # 避免误触发重登、掩盖真实错误（排障手 #7 / 安全官）
            auth_keywords = (
                "登录", "未登录", "重新登录", "登录失效", "unauthorized"
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
                logger.debug("HTTP %s %s (attempt=%s, timeout=%ss)",
                             method, url, attempt + 1, REQUEST_TIMEOUT)
                response = self._session.request(
                    method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
                )
            except requests.exceptions.RequestException as e:
                # 网络层异常：退避后重试
                last_err = e
                if attempt < MAX_NETWORK_RETRIES:
                    time.sleep(NETWORK_BACKOFF[min(attempt, len(NETWORK_BACKOFF) - 1)])
                    continue
                raise MubuError(
                    f"网络连接失败，请检查网络（已重试 {MAX_NETWORK_RETRIES} 次）: {e}",
                    status_code=None,
                )

            # 5xx 服务端错误 → 退避重试（不重登）
            if response.status_code >= 500:
                last_err = None
                if attempt < MAX_NETWORK_RETRIES:
                    time.sleep(NETWORK_BACKOFF[min(attempt, len(NETWORK_BACKOFF) - 1)])
                    continue
                raise MubuError(
                    f"幕布服务暂不可用，请稍后重试（HTTP {response.status_code}，"
                    f"已重试 {MAX_NETWORK_RETRIES} 次仍失败）",
                    status_code=response.status_code,
                    body=response.text,
                )

            # 非 5xx（含 401 等 4xx、2xx）原样返回，交由上层处理
            return response

        # 理论不可达：兜底抛错，避免漏掉 last_err
        raise MubuError(
            f"网络请求失败（非预期）: {last_err or '未知错误'}",
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

        logger.debug("请求 %s %s (auth=%s)", method, endpoint, auth)
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
            # 401 或登录失效类错误，重试后仍失败 → 给出下一步操作指引
            raise MubuError(
                f"登录失效或密码错误，请检查凭据后重试"
                f"（{result.get('msg', '未知错误')}）",
                status_code=response.status_code,
                body=result,
            )

        if result.get("code") != 0:
            # 403 权限不足或其它业务错误，不触发重登
            if response.status_code == 403:
                raise MubuError(
                    f"权限不足，请确认账号权限"
                    f"（{result.get('msg', '未知错误')}）",
                    status_code=response.status_code,
                    body=result,
                )
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

        data = self._request(*ENDPOINTS["login"], auth=False, max_retries=0, json={
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
        data = self._request(*ENDPOINTS["list"], json={"folderId": folder_id})
        return data

    def create_folder(self, name: str, parent_id: str = "0") -> str:
        """创建文件夹"""
        data = self._request(*ENDPOINTS["create_folder"], json={
            "folderId": parent_id,
            "name": name
        })
        return data.get("folder", {}).get("id", "")

    def create_doc(self, name: str, folder_id: str = "0", content: str = "") -> str:
        """创建文档"""
        data = self._request(*ENDPOINTS["create_doc"], json={
            "folderId": folder_id,
            "name": name,
            "content": content
        })
        return data.get("doc", {}).get("id", "")

    def get_doc(self, doc_id: str) -> Dict:
        """获取文档内容"""
        return self._request(*ENDPOINTS["get_doc"], json={"id": doc_id})

    def save_doc(self, doc_id: str, content: str, name: Optional[str] = None) -> None:
        """保存文档"""
        data = {"id": doc_id, "content": content}
        if name:
            data["name"] = name
        self._request(*ENDPOINTS["save_doc"], json=data)

    def delete_folder(self, folder_id: str) -> None:
        """删除文件夹（已真机验证：POST /list/delete_folder，body {"id": ...}）。"""
        self._request(*ENDPOINTS["delete_folder"], json={"id": folder_id})

    def delete_doc(self, doc_id: str) -> None:
        """删除文档（已真机验证：POST /list/delete_doc，body {"id": ...}）。"""
        self._request(*ENDPOINTS["delete_doc"], json={"id": doc_id})

    def delete(self, item_id: str, item_type: str = "folder") -> None:
        """删除文档或文件夹（按类型分发，默认 folder）。

        兼容旧调用；新代码建议直接用 delete_folder / delete_doc。
        """
        if item_type == "doc":
            self.delete_doc(item_id)
        else:
            self.delete_folder(item_id)

    def move(self, item_id: str, target_folder_id: str) -> None:
        """移动文档到其他文件夹"""
        self._request(*ENDPOINTS["move"], json={
            "id": item_id,
            "folderId": target_folder_id
        })

    def rename_doc(self, doc_id: str, new_name: str) -> None:
        """重命名文档（基于现有 save_doc 的 name 参数）。

        先拉取文档内容，再用 save_doc 回写并携带新名称，实现 round-trip 重命名。
        """
        doc = self.get_doc(doc_id)
        content = json.dumps(doc, ensure_ascii=False)
        self.save_doc(doc_id, content, name=new_name)

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        """重命名文件夹（已真机验证：POST /list/rename_folder）。

        实测幕布要求同时携带 ``id`` 与 ``folderId``，且 ``folderId`` 必须填文件夹
        **自身真实 id**（不能填根目录魔法值 ``"0"``，否则返回 code 5）。``name`` 为新名称。
        """
        self._request("POST", "/list/rename_folder", json={
            "id": folder_id,
            "name": new_name,
            "folderId": folder_id,
        })

    def export_tree(self, root_folder_id: str = "0", output_dir: str = ".",
                    max_depth: int = MAX_SEARCH_DEPTH) -> Dict[str, int]:
        """递归导出整个文件夹树为嵌套 Markdown 文件。

        文档写为 ``<name>.md``，子文件夹创建为同级子目录并继续递归。
        单个文件夹/文档拉取失败不阻断整体遍历（记入 errors 统计）。

        Returns:
            {"docs": 导出文档数, "folders": 创建文件夹数, "errors": 失败数}
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        stats: Dict[str, int] = {"docs": 0, "folders": 0, "errors": 0}

        def walk(folder_id: str, current_dir: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                data = self.get_list(folder_id)
            except MubuError as e:
                logger.warning("导出遍历文件夹 %s 失败: %s", folder_id, e)
                stats["errors"] += 1
                return
            folders = data.get("folders", []) or []
            docs = data.get("documents") or data.get("docs") or []
            for d in docs:
                doc_id = d.get("id")
                name = (d.get("name") or "untitled").strip()
                try:
                    doc = self.get_doc(doc_id)
                    md = export_markdown(doc)
                    safe_name = _safe_filename(name)
                    (current_dir / f"{safe_name}.md").write_text(md, encoding="utf-8")
                    stats["docs"] += 1
                except MubuError as e:
                    logger.warning("导出文档 %s 失败: %s", doc_id, e)
                    stats["errors"] += 1
            for f in folders:
                fid = f.get("id")
                fname = (f.get("name") or "untitled").strip()
                child_dir = current_dir / _safe_filename(fname)
                child_dir.mkdir(parents=True, exist_ok=True)
                stats["folders"] += 1
                walk(fid, child_dir, depth + 1)

        walk(root_folder_id, output_path, 0)
        return stats

    def search(self, keyword: str, root_folder_id: str = "0",
               max_depth: int = MAX_SEARCH_DEPTH,
               limit: int = MAX_SEARCH_LIMIT,
               max_requests: int = MAX_SEARCH_REQUESTS) -> Dict[str, Any]:
        """本地递归搜索：名称包含关键字的文档与文件夹（T6，M4 T2 增强）。

        mubu 无公开 /search 端点，从根文件夹开始递归遍历所有子文件夹，
        收集 name 包含 keyword（大小写不敏感）的条目。

        为保护调用方，到达以下任一上限即停止遍历并标记 truncated=True
        （不再静默丢失信息，调用方据此知晓结果可能不完整）：
        - max_depth: 递归深度上限（根 depth=0，默认 3 即最多展开 4 层）
        - limit: 返回结果总数上限
        - max_requests: 整个搜索的 get_list 请求数硬上限

        环检测：已访问的 folder_id 进入 visited 集合，遇到重复引用直接跳过，
        防止幕布返回环引用时无限递归（max_requests 之上的第二道防线）。

        Args:
            keyword: 搜索关键字（大小写不敏感）
            root_folder_id: 遍历起点文件夹 ID，默认 "0"（根）
            max_depth: 递归深度上限
            limit: 返回结果总数上限
            max_requests: 搜索总请求数硬上限

        Returns:
            字典 {"results": [...], "truncated": bool, "limit": int, "max_depth": int}
            - results: 匹配项列表，每项含 id / name / type（"doc" | "folder"）
              / path（从根起的路径）
            - truncated: 是否因达到上限而提前结束（结果可能不完整）
        """
        keyword_lower = (keyword or "").lower()
        results: List[Dict[str, Any]] = []
        req_count = 0
        truncated = False
        visited: set = set()  # 已访问 folder_id，防环引用无限递归

        def walk(folder_id: str, path: str, depth: int) -> None:
            nonlocal req_count, truncated
            if folder_id in visited:
                return  # 已访问，去重（防环）
            visited.add(folder_id)
            if truncated or depth > max_depth or req_count >= max_requests:
                if depth > max_depth or req_count >= max_requests:
                    truncated = True
                return
            try:
                data = self.get_list(folder_id)
            except MubuError as e:
                # 单个文件夹拉取失败不阻断整体遍历
                logger.warning("遍历文件夹 %s 失败: %s", folder_id, e)
                return
            req_count += 1
            if len(results) >= limit:
                truncated = True
                return
            folders = data.get("folders", []) or []
            docs = data.get("documents") or data.get("docs") or []
            for d in docs:
                name = d.get("name") or ""
                if keyword_lower and keyword_lower in name.lower():
                    results.append({"id": d.get("id"), "name": name, "type": "doc", "path": path})
                    if len(results) >= limit:
                        truncated = True
                        return
            for f in folders:
                name = f.get("name") or ""
                if keyword_lower and keyword_lower in name.lower():
                    results.append({"id": f.get("id"), "name": name, "type": "folder", "path": path})
                    if len(results) >= limit:
                        truncated = True
                        return
                child_path = f"{path}/{name}" if path else name
                walk(f.get("id"), child_path, depth + 1)

        walk(root_folder_id, "", 0)
        return {
            "results": results,
            "truncated": truncated,
            "limit": limit,
            "max_depth": max_depth,
        }
