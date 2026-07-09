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
- P2-6：_save_token 增加 fcntl.flock 跨进程 advisory 锁
- P1-4 / P2-7：补充网络层（5xx 混合降级、ConnectionError）与 .env 回归测试
- P0-1：SKILL.md 清理旧版独立函数，改为指向 MubuClient 的引用与示例
