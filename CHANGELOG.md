# Changelog

记录 mubu-integration Skill 的里程碑演化。

## M1 (P0) — 基础能力
- 登录（手机号密码 → JWT Token，请求头 `jwt-token`）
- 文档/文件夹 CRUD：create_folder / create_doc / get_doc / save_doc / delete / move
- Markdown 双向：doc_to_markdown / export_markdown / markdown_to_doc（含 note 备注、勾选 [x] 往返）
- Token 本地缓存 + 临近过期自动重登（仅重试 1 次，杜绝死循环）
- 发布 GitHub tag 1.0.0

## M2 (P1) — 网络健壮性 + 本地搜索
- 网络层 5xx 指数退避重试（最多 2 次，与 401 重登分层互不干扰）
- 非 JSON 响应友好异常 + body 截断
- .env 凭据加载（仅环境变量未设置时补全）
- Token 文件权限 0o600（原子写 + chmod）
- 本地搜索 search()（递归遍历 + 按名称过滤）+ CLI search 子命令
- 发布 ClawHub v1.1.0

## M3 (P2) — 工程化收尾
- scripts/mubu_api.py 全量类型注解（typing 模块，Python 3.8+ 兼容，100% 覆盖）
- 新增 requirements.txt（requests + pytest + responses，.env.mubu 手写解析无 dotenv 依赖）
- 新增 .github/workflows/test.yml CI（push/PR 触发，Python 3.9–3.12 矩阵，41 用例全过）
- README 美化：CI 状态徽章、架构/双向转换 Mermaid 图、30 秒快速体验、FAQ

## M4 (P0/P1/P2) — 完善阶段（本期）
- P1-5：ENDPOINTS 元组化 (method, path)，消除调用点硬编码 "POST"
- P0-2：search() 增加 max_depth / limit / max_requests 上限；CLI 透传 --max-depth / --limit
- P1-3：_http_request 兜底消息避免渲染字面 : None
- P2-6：_save_token 增加 fcntl.flock 跨进程 advisory 锁（已加固为跨平台安全：try/except ImportError，无 fcntl 平台如 Windows 降级为无锁）
- P1-4 / P2-7：补充网络层（5xx 混合降级、ConnectionError）与 .env 回归测试
- P0-1：SKILL.md 清理旧版独立函数，改为指向 MubuClient 的引用与示例
- T2 收尾：新增 `test_search_global_limit_enforced`，真实验证 `search()` 全局 `limit` 上限被强制执行（破坏性验证：移除上限逻辑则用例失败）
- SKILL.md「Token 管理建议」示例修正：朴素 `open()+json.dump` 改为原子写（tempfile + os.replace）+ chmod 0o600，并注明真实 `_save_token` 还含跨进程 fcntl 锁；删除误导性的 `is_token_valid`

## M5 (审计整改) — ClawHub Security Audit 全量修复（1 High + 6 Medium）
- **High · 供应链（依赖未锁定 CVE）**：`requirements.txt` `requests>=2.28,<3` → `requests>=2.32.4,<3`，修复 CVE-2024-47081（.netrc 凭据泄漏）、CVE-2024-35195（Session 复用 `verify` 被覆盖）。CVE-2026-25645（extract_zipped_paths 临时文件复用）经核查本代码路径不可达，仅作升级加固。
- **Medium · MCP 最小权限（Lp3）**：SKILL.md 新增 `## 权限与安全边界` 段落，明确声明只读/写入/网络/破坏性操作需确认/信任边界 5 条约束。
- **Medium · 触发词歧义（Vague Triggers ×2）**：frontmatter `description` 与激活指引触发词收窄为 `幕布、mubu、幕布同步、幕布大纲导出`，移除易误触的 `大纲笔记`、`思维导图导出`；全仓 grep 复核 0 残留。
- **Medium · 缺失破坏性操作警示（Missing User Warnings ×3）**：`delete` 增加 `⚠️ 删除不可逆` 明确提示；CLI 增加 `--yes` 显式确认标志，`main()` 删除分支硬拦截（未传 `--yes` 则打印警示并 `sys.exit(1)`，0 网络请求）。README 删除示例同步更新为 `delete <id> --yes`。
- **验证**：pytest 45 用例全过；`py_compile` 通过；QA 独立 monkeypatch 复验确认 delete 无 `--yes` 时实际发出 0 次网络请求；7 项审计发现全部 RESOLVED，路由判定 NoOne。
- 发布 ClawHub v1.1.4（清除 Review 状态）。

## M6 (遗留清理) — 根节点 note 导出修复
- 修复 `export_markdown()` 遗漏根节点 note 输出的 Bug：children 循环后追加 `f"> {note}"`（与子节点 note 格式一致）。
- 新增 3 个测试：根 note 存在性与位置（在 children 之后）、空 note 省略（不产生孤立 `> ` 行）、含根 note 文档往返一致性（md→doc→md）。
- 工程师 IS_PASS YES，QA 独立验证 48/48 全过（45 既有 + 3 新增），路由 NoOne。
- 发布 ClawHub v1.1.5。

## M7 (审计补充) — pytest CVE 版本锁定
- `requirements.txt` `pytest>=7,<9` → `pytest>=8.3.5,<9`，修复 CVE-2025-71176（pytest tmpdir 处理漏洞；仅测试依赖，运行时不受影响）。
- 48/48 测试全过（pytest 8.x 兼容）。
- 发布 ClawHub v1.1.6。
