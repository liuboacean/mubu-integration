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
- P0-2：search() 上限（max_depth / limit / max_requests）经核实仓库原版已具备，CLI 透传 --max-depth / --limit（本期仅核对确认，非新增）
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

## M8 (安全加固) — 凭据 / 路径 / 文档一致性（本期）
- **安全官 #1/#2/#12**：`.env.mubu` 加载时强制 `chmod 0o600`；CLI 移除 `--phone`/`--password` 明文参数，凭据改由环境变量 / `.env.mubu` 提供，`login` 子命令缺失时交互式 `getpass` 输入密码；SKILL.md 删除"直接在脚本中配置"类表述。
- **安全官 #3**：新增 `_safe_local_path()`，在 `create --md` / `save --file` 读取本地文件前校验路径——拒绝绝对路径、`..` 越界路径及当前工作目录之外的路径，防任意文件读取外发。
- **安全官 #8 / 排障手 #8**：实现 `MUBU_BASE_URL` 环境变量覆盖，仅限 `mubu.com` 家族域名白名单（防 MITM 指向恶意服务器）；SKILL.md「网络」边界说明同步更新。
- **排障手 #7**：收紧 `_is_auth_error` 关键字匹配（移除 "token"/"auth"/"expire"/"login"/"过期" 等泛化词，仅保留明确登录失效短语），避免正常业务错误误触发重登。
- **He H3**：`_http_request` 兜底消息避免渲染字面 `None`（非预期 + `last_err or '未知错误'`）。
- **文档一致性**：CONTRIBUTING 修正开发/运行指令（`git clone` + `pip install -r requirements.txt` + `PYTHONPATH=scripts python -m pytest -v` + 入口 `python3 scripts/mubu_api.py`）；README 版本号统一为 v1.1.6、测试数统一为 69、去除割裂的双版本叙事。
- **测试补充（排障手 #5/#6、He H4）**：新增真实 API 方法 payload 单测（create_folder/create_doc/get_doc/save_doc/delete/move 的请求体 JSON 与返回 id 提取）、`delete --yes` 守卫回归（无 `--yes` 0 网络调用且 `sys.exit(1)`）、`login` CLI 无明文参数 + getpass 交互测试；全量测试 69 用例通过（48 既有 + 20 新增 + 1 路径校验补强）。
- **说明**：`search()` 的 `max_depth`/`limit`/`max_requests` 上限经核实为仓库原版已具备（非本期新增），对应方案 He H2 审计结论已修正。
- （已随 v1.2.0 发布；详情见文末「v1.2.0」段。）

## M9 (P1 第一批) — 产品文案 / 错误指引 / 日志 / 搜索截断 / CI 加固

- **产品官 #10/#11/#15**：README「双向同步」表述改为「Markdown 导入/导出（往返保真）」，明确说明**非**真正双向同步（无 diff/merge，重复导入生成新副本），并加 true-sync「不在本期范围」说明；README 顶部新增显眼「第一步：配置凭据」块（环境变量 / `~/.workbuddy/.env.mubu`，不假设用户已就绪）；新增 `examples/weekly.md` 示例大纲供 `create --md examples/weekly.md` 直接体验。SKILL.md 同步修正「幕布同步」触发词与 `search()` 示例（`["results"]` 解包）。
- **产品官+排障手 #15 / 错误操作指引**：`_http_request` / `_request` 按 HTTP 状态码给出下一步文案并打到 stderr——401→「登录失效或密码错误，请检查凭据后重试」；403→「权限不足，请确认账号权限」；5xx→「幕布服务暂不可用，请稍后重试」；网络异常→「网络连接失败，请检查网络」。
- **排障手 #17 / 搜索截断 + 环检测**：`search()` 返回值由 `List` 改为含 `truncated: bool` 的字典结构（`{"results", "truncated", "limit", "max_depth"}`），到达 `limit`/`max_depth`/`max_requests` 上限时标记 `truncated=True`（不再静默丢失）；新增已访问 `folder_id` 的 `visited` 集合去重，防止幕布环引用导致无限递归（双保险）。`main()` 与测试同步适配，调用方可知结果不完整。
- **排障手 #19 / 移除冗余 ensure_login**：`get_list`/`create_folder`/`create_doc`/`get_doc`/`save_doc`/`delete`/`move` 移除冗余 `ensure_login()` 调用，统一走 `auth=True`（`_request` 内 `ensure_valid_token` 已处理），行为不变；`ensure_login` 方法保留作兼容。
- **排障手+安全官 #16 / 日志规范**：引入 `logging` 取代散落 `print`；`warning`/`error` 分级，CLI 加 `--verbose` 开关控制 `debug`；异常只记 `msg`、不记请求/响应体（`body` 200 字符截断保留），确认明文密码 / token 不进日志。
- **安全官 #20 / CI hash pinning + Dependabot**：`.github/workflows/test.yml` 将 `actions/checkout@v4` 锁定为完整 commit SHA `11bd71901bbe5b1630ceea73d27597364c9af683`(v4.2.2)、`actions/setup-python@v5` 锁定为 `a26af69be951a213d495a4c3e4e4022e16d87065`(v5)，并加最小 `permissions: contents: read`；新增 `.github/dependabot.yml` 启用 GitHub Actions 与 pip 依赖每周自动更新 PR（SHA 钉死由人工 review 确认）。
- **测试补充（+11，共 80）**：搜索 `truncated` 标记（limit 命中 / 环检测无无限递归）、错误指引 4 类状态码文案、ensure_login 冗余已移除（2 处不触发 ensure_login 调用）、日志脱敏（明文密码不进日志）+ `--verbose` 启用 debug、`examples/weekly.md` 可解析。全量测试 **80 用例通过**（69 既有 + 11 新增）。
- 已随 **v1.2.0** 发布（GitHub tag v1.2.0，2026-07-14）。

## v1.2.0（本期发布版本 · 2026-07-14）

本期合并发布 **M8（安全加固）+ M9（P1 第一批：产品文案 / 错误指引 / 日志 / 搜索截断 / CI）+ P2（工程化增强）**，构成自 v1.1.6 以来的完整能力跃升（GitHub tag v1.2.0）。

- **安全（M8）**：凭据文件强制 `0o600`、移除明文 CLI 参数改交互式 `getpass`、本地路径越界防护 `_safe_local_path`、API 域名白名单（`MUBU_BASE_URL` 仅限 mubu.com 家族）防 MITM。
- **健壮性（M9）**：`search()` 返回含 `truncated: bool` 并加 `visited` 集合防环；标准 `logging` + 敏感信息脱敏 + `--verbose`；401/403/5xx/网络错误打到 stderr 的下一步指引；CI 钉死 `actions/checkout@v4` / `actions/setup-python@v5` 完整 SHA + 新增 Dependabot 周更。
- **工程化（P2）**：`MubuClient` 复用 `requests.Session` 连接池；依赖拆分为 `requirements.txt`（运行时）+ `requirements-dev.txt`（pytest / responses `<1`）；新增本 Roadmap 段。
- 测试覆盖：**84 用例全过**（69 P0 基线 + 11 P1 + 4 P2），CI 矩阵 Python 3.9–3.12。
- 删除操作保留 `--yes` 守卫与「不可逆」stderr 警示（无回收站，软删除待幕布 API 能力确认）。

## M10 (Roadmap 实施) — 整树导出 / 重命名 / OPML·FreeMind（本期）

- **整树导出**：新增 `MubuClient.export_tree(root_folder_id, output_dir, max_depth)` 与 CLI `export-tree` 子命令，递归遍历文件夹树并将每个文档写为 `<name>.md`，子文件夹创建为同级子目录；单点拉取失败不阻断整体遍历（记入 `errors` 统计）。
- **重命名**：新增 `rename_doc(doc_id, new_name)`（走 `save_doc` 的 `name` 参数，round-trip 保内容）+ CLI `rename --type doc`；新增 `rename_folder(folder_id, new_name)` 走逆向推测端点 `/list/update_folder`（幕布无官方 API 文档，真实环境需验证），对应 CLI `rename --type folder`。
- **OPML / FreeMind 导出**：新增模块级 `doc_to_opml(doc)` / `doc_to_freeplane(doc)` 与 CLI `opml <doc_id> --format opml|freeplane`，将幕布大纲转为 OPML 2.0 / FreeMind XML，兼容 XMind 等其它大纲工具。
- **软删除降级说明**：幕布回收站 API 未文档化，本期维持 `delete` 硬删 + `--yes` 守卫 + 「不可逆」stderr 警示，**不实现软删除**（避免引入未经证实的 API 调用）。
- **测试补充（+9，共 93）**：export_tree 嵌套文件生成 / 单点失败处理、rename_doc 调 save 带 name / rename_folder 走推测端点、doc_to_opml / doc_to_freeplane 合法 XML、_safe_filename 非法字符替换。全量测试 **93 用例通过**。
- 模块拆分（单文件 → 包）已在 M11 完成。

## M11 (Roadmap · 大重构) — 模块拆分（单文件 → 包，非 breaking）

将单文件 `scripts/mubu_api.py` 按职责拆分为正式 Python 包 `scripts/mubu/`，`mubu_api.py` 降级为向后兼容 shim（重新导出全部公开符号），**对外接口零破坏**。

- **`scripts/mubu/config.py`**：常量 / 配置（`DEFAULT_BASE_URL` / `ENDPOINTS` / 重试与搜索上限）、日志、异常 `MubuError`、路径安全 `_safe_local_path`、Token 文件锁 `_token_file_lock`、域名白名单解析。
- **`scripts/mubu/convert.py`**：文档结构 ↔ Markdown / OPML / FreeMind 转换（`doc_to_markdown` / `export_markdown` / `markdown_to_doc` / `doc_to_opml` / `doc_to_freeplane`）与展示格式化（`_safe_filename` / `format_list` / `format_search`）。
- **`scripts/mubu/client.py`**：`MubuClient`（鉴权 / 请求 / 文档·文件夹·搜索·整树导出）。
- **`scripts/mubu/cli.py`**：命令行入口 `main()` + `_configure_logging()`。
- **`scripts/mubu/__init__.py`**：包标识（`__version__ = "1.3.0"`）。
- **`scripts/mubu_api.py`（shim）**：`from mubu.* import ...` 重新导出全部公开符号（含 `os` / `sys` / `json` / `Path` 等标准库模块级名称，保持旧调用方与既有测试兼容）；`__main__` 仍调用 `main()`。

**兼容性验证**：
- `import mubu_api` 及其公开符号（`MubuClient` / `MubuError` / `doc_to_markdown` / ...）全部可用；`python scripts/mubu_api.py <subcommand>` 行为不变。
- 新增包内导入路径：`from mubu.client import MubuClient`、`from mubu.convert import export_markdown`、`from mubu.config import MubuError` 等均可独立使用。
- 既有测试适配：因 `os` / `getpass` 为单例模块，`monkeypatch(mubu_api.os / mubu_api.getpass)` 仍生效；函数 / `Path` / `TOKEN_FILE` / `ENV_FILE` 的 patch 目标修正为使用点（`mubu.cli.*`、`mubu.client.TOKEN_FILE`、`mubu.client.ENV_FILE`、`mubu.config.Path`）。全量测试 **93 用例通过**（无用例增减，纯结构重构）。

## Roadmap（向前展望，尚未实现）

以下为已识别、尚未排入实施的能力增强与重构方向，供后续迭代参考：

- **模块拆分（排障手 #18）**：✅ 已在 M11 完成——`scripts/mubu_api.py` 拆分为 `scripts/mubu/`（config / convert / client / cli），`mubu_api.py` 保留为向后兼容 shim，93 用例通过。
- **文件夹重命名 / 移动增强（产品官 #14）**：补全 `rename_folder` 等高层方法，提升目录管理能力。
- **整树递归导出（产品官 #14）**：支持将整个文件夹树递归导出为单一 Markdown / JSON，便于整体备份。
- **软删除 / 回收站（产品官 #14 P2）**：当前 `delete` 为永久删除（已加 `--yes` 守卫与不可逆警示）；若幕布开放回收站接口，可增加软删除通道。
- **互操作导出（产品官 #25）**：导出支持 OPML / FreeMind 格式，便于导入到其他大纲工具。
- **依赖锁文件（排障手 #21）**：引入 `pip-tools` 生成 `requirements.lock.txt`，配合 `--require-hashes` 进一步提升供应链可复现性。

