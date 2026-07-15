"""mubu 包 — 配置、常量、日志、异常与路径安全基础设施。"""
import os
import sys
import json
import time
import logging
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlparse
from typing import Optional, Dict, List, Any, Tuple, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # 无 fcntl 平台（如 Windows）：锁降级为无操作

# --------------------------------------------------------------------------- #
# 日志（P1 #16）：用 logging 取代散落的 print；warning/error 分级，
# --verbose 控制 debug；敏感内容（密码 / token）绝不进日志。
# --------------------------------------------------------------------------- #
logger = logging.getLogger("mubu_api")
logger.propagate = False  # 不外传至 root，避免重复输出
if not logger.handlers:
    # 默认 stderr 处理器（导入期或尚未经 main() 配置时也能输出 warning/error）
    _default_handler = logging.StreamHandler(sys.stderr)
    _default_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(_default_handler)
logger.setLevel(logging.WARNING)

# API 基础配置
# 默认 base URL；允许通过环境变量 MUBU_BASE_URL 覆盖，但仅限 mubu.com 家族域名，
# 防止指向恶意服务器造成 MITM / 凭据泄漏（安全官 #8）。
DEFAULT_BASE_URL = "https://api2.mubu.com/v3/api"
ALLOWED_BASE_HOSTS = ("api2.mubu.com", "api.mubu.com", "mubu.com")


def _resolve_base_url() -> str:
    """解析 base URL：优先 MUBU_BASE_URL，但仅接受 mubu.com 家族域名。

    域名不在白名单时拒绝覆盖、回退默认并 stderr 告警（不静默信任），
    避免攻击者通过环境变量将流量导向伪造服务器。
    """
    env_url = os.getenv("MUBU_BASE_URL")
    if not env_url:
        return DEFAULT_BASE_URL
    try:
        host = urlparse(env_url).hostname or ""
    except Exception:
        host = ""
    if host in ALLOWED_BASE_HOSTS:
        return env_url.rstrip("/")
    logger.warning(
        "MUBU_BASE_URL 域名 '%s' 不在允许列表（仅限 mubu.com 家族），"
        "已忽略并使用默认地址 %s",
        host, DEFAULT_BASE_URL,
    )
    return DEFAULT_BASE_URL


BASE_URL = _resolve_base_url()
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

# 接口路径常量：统一在此维护，便于后续集中修改。
# 每个端点为 (HTTP 方法, 路径) 二元组；调用处用 self._request(*ENDPOINTS["key"], ...) 解包。
ENDPOINTS = {
    "login": ("POST", "/user/phone_login"),
    "list": ("POST", "/list/get"),
    "create_folder": ("POST", "/list/create_folder"),
    "create_doc": ("POST", "/list/create_doc"),
    "get_doc": ("POST", "/document/edit/get"),
    "save_doc": ("POST", "/doc/save"),
    # 真机验证（2026-07-15）：删除必须区分类型，且端点为 delete_folder / delete_doc，
    # 原推测的 /list/delete 实测返回 code 17 illegal request。
    "delete_folder": ("POST", "/list/delete_folder"),
    "delete_doc": ("POST", "/list/delete_doc"),
    # move 端点尚未经真机验证（返回 illegal request），保留原推测值，待抓包确认
    "move": ("POST", "/list/move"),
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

# 本地搜索（search）限制配置（M4 T2）
# 根文件夹 depth=0，默认 3 即最多展开 4 层
MAX_SEARCH_DEPTH = 3
# 返回结果总数上限（单轮 search 命中条目硬上限，达到即静默截断）
MAX_SEARCH_LIMIT = 50
# 整个搜索的 HTTP 请求数硬上限（get_list 调用次数）
MAX_SEARCH_REQUESTS = 200


# Token 文件跨进程 advisory 锁（P2-6）：Unix 用 fcntl.flock；无 fcntl 平台降级为无操作
@contextmanager
def _token_file_lock() -> Iterator[None]:
    """用 fcntl.flock 对 Token 文件加排他锁，避免多进程并发写损坏文件。

    锁文件为 TOKEN_FILE 同目录下的 ``<name>.lock``；进入临界区前 flock(LOCK_EX)，
    退出（含异常）时 flock(LOCK_UN)，异常路径保证锁释放。
    无 fcntl 平台（如 Windows）：跳过加锁，仅单进程场景下依赖原子 rename 保证完整性。
    """
    if fcntl is None:
        yield          # 无 fcntl：跳过加锁，仅单进程场景（原子 rename 仍保证完整性）
        return
    lock_path = TOKEN_FILE.parent / (TOKEN_FILE.name + ".lock")
    f = open(lock_path, "a")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()


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


def _safe_local_path(path: str) -> Path:
    """校验并解析本地文件路径，仅允许当前工作目录或其子目录（安全官 #3）。

    拒绝绝对路径、``..`` 越界路径、以及跳出当前工作目录的路径，防止
    ``create --md`` / ``save --file`` 读取 ``/etc/passwd``、``~/.ssh/id_rsa``
    等任意文件并外发。校验失败抛 MubuError（清晰错误，而非原始栈）。
    """
    # 0) 展开 ~ 为用户目录（如 ~/.ssh/id_rsa → /Users/.../.ssh/id_rsa），
    #    展开后若为绝对路径将在下一步被明确拒绝，避免被静默解析为 cwd 下文件。
    path = os.path.expanduser(path)
    # 1) 拒绝越界片段（.. 跳出目录层级）
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise MubuError(f"拒绝越界路径（包含 '..'）: {path}")
    # 2) 拒绝绝对路径
    if os.path.isabs(path):
        raise MubuError(f"拒绝读取绝对路径（可能越权访问系统文件）: {path}")
    # 3) 解析后的真实路径必须位于当前工作目录内（含其自身，symlink 已被 realpath 展开）
    resolved = os.path.realpath(path)
    cwd = os.path.realpath(os.getcwd())
    if resolved != cwd and not resolved.startswith(cwd + os.sep):
        raise MubuError(f"拒绝访问允许目录（当前工作目录）之外的文件: {path}")
    return Path(resolved)
