# Changelog — mubu-integration (幕布 Skill)

本文档记录 mubu-integration Skill 各里程碑的关键变更。

## M1 — 基础 API 封装与 CLI

- 实现 `MubuClient` 核心客户端与登录 / 文档 / 文件夹基础 API 封装。
- 提供 `doc_to_markdown` / `export_markdown` / `markdown_to_doc` 真正的 Markdown 往返转换（非占位）。
- 新增 `move` 子命令与 CLI 入口。

## M2 — 认证 / Token 持久化与刷新

- 引入 `.env` 凭据加载（`~/.workbuddy/.env.mubu`，仅环境变量未设置时补全）。
- Token 本地持久化：原子写（`.tmp` + `os.rename`）+ 权限 `0o600`。
- Token 临近过期自动重登刷新（不依赖 refresh_token）；401 / 登录失效仅重试 1 次，杜绝死循环。
- 网络健壮性：`_request` 增加 `timeout=15`、非 JSON 响应友好异常、网络层 / 5xx 指数退避重试（最多 2 次，与鉴权重试分层互不干扰）。
- 本地搜索 `search()`：从根文件夹递归遍历、按名称本地过滤（mubu 无公开搜索端点），CLI 新增 `search` 子命令。

## M3 — 工程化收尾：补全类型注解、requirements.txt、GitHub Actions CI

- 为 `scripts/mubu_api.py` 补全完整类型注解（函数签名、返回值、`Optional` / `Dict` / `List` 等）。
- 新增 `requirements.txt`（运行时 `requests` + 测试 `pytest` / `responses`）。
- 新增 `.github/workflows/test.yml`：GitHub Actions 矩阵（Python 3.9–3.12）自动运行 `PYTHONPATH=scripts python -m pytest -v`。

## M4 — 根据外部评审完善 8 项

- **ENDPOINTS 方法标注**（P1-5）：`ENDPOINTS` 由「路径字符串」改为「(HTTP 方法, 路径)」二元组，调用点统一用 `self._request(*ENDPOINTS["key"], ...)` 解包。
- **search 深度 / 数量限制**（P0-2）：新增 `MAX_SEARCH_DEPTH` / `MAX_SEARCH_LIMIT` / `MAX_SEARCH_REQUESTS` 常量与 `search(max_depth, limit, max_requests)` 参数，递归遍历中做静默截断（超深 / 超量 / 超请求数即停止）；CLI `search` 增加 `--max-depth` / `--limit` 透传。
- **网络回退信息优化**（P1-3）：`_http_request` 重试耗尽后的兜底报错改为 `网络请求失败（已耗尽重试）: <last_err 或 未知错误>`。
- **token 文件锁**（P2-6）：新增 Unix 专用跨进程文件锁 `_token_file_lock`（基于 `fcntl.flock`，Windows 降级为无锁），包裹 `_save_token` 原子写。
- **网络健壮性测试**（P1-4）：新增 `test_5xx_mixed_degrade_then_success` / `test_connection_error_retries_then_success`，验证 5xx / 连接错误降级重试后恢复。
- **env 解析回归**（P2-7）：新增 `test_env_key_stripped`，证明 `.env.mubu` 中 `KEY = VALUE` 的 `=` 两侧空白被正确 `.strip()`。
- **SKILL.md 过时代码清理**（P0-1）：删除第 46–253 行残留的旧版独立函数示例（与 `MubuClient` 不一致、返回值用旧 `data["user"]["id"]`），替换为简洁的「使用 MubuClient」扁平结构最小示例。
- **CHANGELOG 建立**（P2-8）：新建本文件，记录 M1–M4 里程碑。
