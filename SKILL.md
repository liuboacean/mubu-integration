---
name: mubu-integration
description: 幕布笔记集成，支持登录认证、文档管理、文件夹操作、大纲导入/导出等功能。触发词：幕布、mubu、幕布大纲导入导出
---

# 幕布集成 Skill

幕布（mubu.com）是一款极简大纲工具，支持将大纲一键转为思维导图。本 Skill 提供 API 集成能力。

## 权限与安全边界
本 Skill 以你的幕布账号身份操作**远程真实内容**，使用前请知悉其权限边界：
- **读取**：仅读取环境变量 `MUBU_PHONE` / `MUBU_PASSWORD`（环境变量未设置时，才由仓库外的 `~/.workbuddy/.env.mubu` 补全，且不写回其它位置）。
- **写入**：仅在本地写入 Token 缓存文件 `~/.mubu_token`（权限 `0o600` + 跨进程 `fcntl` 锁），不写入其它文件。
- **网络**：仅访问 `api2.mubu.com`（base URL 可由 `MUBU_BASE_URL` 覆盖，但仅限 `mubu.com` 家族域名，防 MITM），**无第三方服务、无遥测、无数据外发**。
- **破坏性操作需确认**：`save` / `move` / `delete` 会修改或删除你在幕布上的真实文档；其中 `delete` 为不可逆操作，CLI 必须显式传 `--yes` 才执行，否则中止并提示。
- **信任边界**：Skill 不读取你的其它本地文件、不执行与幕布无关的 shell 命令；它只做「登录 → 读写你的幕布文档」这一件事。

## 功能概览

| 功能 | 接口 | 说明 |
|------|------|------|
| 用户登录 | `POST /user/phone_login` | 手机号密码登录获取 Token |
| Token 刷新 | 自动处理 | access_token 2小时过期，临近过期自动重新登录（重登仅重试 1 次，杜绝死循环） |
| 创建文件夹 | `POST /list/create_folder` | 在指定位置创建文件夹 |
| 创建文档 | `POST /list/create_doc` | 创建新的大纲文档 |
| 获取列表 | `POST /list/get` | 获取文件夹下的文档列表 |
| 获取文档 | `POST /document/edit/get` | 获取文档详细内容（真实端点；body 为 docId+password+isFromDocDir，返回 data.definition 为 JSON 字符串需二次解析） |
| 更新文档 | `POST /doc/save` | 保存/更新文档内容 |
| 删除文档 | `POST /list/delete_doc` | 删除文档（按类型区分端点） |
| 删除文件夹 | `POST /list/delete_folder` | 删除文件夹（原 `/list/delete` 实测非法，已弃用） |
| 移动文档 | `POST /list/move` | 移动文档到其他文件夹（⚠️ 端点未实测验证） |
| 导出 Markdown | 本地转换 | 将大纲结构转换为 Markdown |

## API 基础信息

- **Base URL**: `https://api2.mubu.com/v3/api`
- **认证方式**: JWT Token，通过请求头 `Jwt-Token` 传递
- **Content-Type**: `application/json;charset=UTF-8`

## 环境变量配置

在使用前，需要配置以下环境变量：

```bash
export MUBU_PHONE="your_phone_number"    # 幕布账号手机号
export MUBU_PASSWORD="your_password"      # 幕布账号密码
```

> 切勿在脚本或代码中硬编码明文密码；凭据仅通过环境变量或仓库外的
> `~/.workbuddy/.env.mubu` 提供。

---

## 使用说明

### 1. 使用 MubuClient

所有操作都通过 `scripts/mubu_api.py` 中的 `MubuClient` 类完成（**不再有**独立的
`login()` / `create_folder()` / `create_doc()` / `get_list()` / `get_doc()` / `save_doc()` /
`delete_item()` 模块级函数）。实例化时自动读取 `MUBU_PHONE` / `MUBU_PASSWORD`
环境变量（或 `~/.workbuddy/.env.mubu`）并加载本地缓存 Token：

```python
from scripts.mubu_api import MubuClient

# 登录：凭据来自环境变量；返回扁平 data（token / id / name）
client = MubuClient()
info = client.login()
print(info["user_id"], info["username"])   # 注意是扁平 data["id"]，非 data["user"]["id"]

# 按名称本地搜索文档/文件夹（递归遍历，大小写不敏感）
results = client.search("项目", max_depth=3, limit=50)["results"]
for r in results:
    print(r["type"], r["name"], r["path"])
```

> 登录返回结构为**扁平** `data`：`data["id"]`=用户 ID，`data["name"]`=用户名，
> `data["token"]`=令牌。这与旧版嵌套 `result["data"]["user"]["id"]` 不同。

---

## 大纲内容格式

幕布文档内容使用特定的 JSON 格式表示大纲结构：

```json
{
  "node": {
    "id": "root",
    "text": "文档标题",
    "children": [
      {
        "id": "node_1",
        "text": "一级标题",
        "children": [
          {
            "id": "node_1_1",
            "text": "二级标题",
            "children": []
          }
        ]
      },
      {
        "id": "node_2",
        "text": "另一个一级标题",
        "children": []
      }
    ]
  }
}
```

---

## Token 管理建议

由于幕布的 access_token 仅约 2 小时有效（无 refresh_token 机制，代码也无任何 refresh 逻辑），建议：

1. **本地缓存**: 将 Token 保存到本地文件（如 `~/.mubu_token`）
2. **自动刷新**: 在 Token 快过期时自动刷新
3. **错误重试**: 遇到 401 错误时重新登录

```python
import os
import time
import json
import tempfile

TOKEN_FILE = os.path.expanduser("~/.mubu_token")

def save_token(token_data):
    """原子写 + 仅属主可读写：避免中途崩溃留下残缺文件，并防止其它用户读取。"""
    token_data = dict(token_data)
    token_data["expires_at"] = time.time() + 7200  # 2小时后过期
    # 注：真实 scripts/mubu_api.py 的 _save_token 还会用跨进程 fcntl.flock
    # advisory 锁包裹整段写（M4 已做成跨平台安全：无 fcntl 平台降级为无锁）；
    # 此处省略锁，聚焦写盘逻辑。
    dir_name = os.path.dirname(TOKEN_FILE) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_name, prefix=".mubu_token.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(token_data, f)
        os.chmod(tmp, 0o600)        # 仅属主可读写
        os.replace(tmp, TOKEN_FILE) # 原子重命名，避免残缺文件
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

def load_token():
    """从本地加载未过期的 Token；已过期或损坏则返回 None。"""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
    except Exception:
        return None
    if time.time() >= data.get("expires_at", 0):  # 已过期视为无效
        return None
    return data
```

说明：原示例中朴素的 `is_token_valid` 已移除——其职责（"是否过期"）已并入 `load_token`，仅返回未过期的 token。真实实现 `scripts/mubu_api.py` 的 `_save_token` 还包含跨进程 `fcntl.flock` 锁与统一的 `TOKEN_FILE_MODE` 权限管理，此处不再重复。

---

## 导出 / 导入 Markdown

M1 已落地真正的 Markdown 导入/导出（往返保真，不再是占位）。核心纯函数位于 `scripts/mubu_api.py`：

```python
def doc_to_markdown(node, level=0):
    """将节点（及子树）渲染为 Markdown 列表片段。
    '- ' 列表项，缩进 = 2 * level；含 checked → '- [x]'/'- [ ]'；
    含 note → 子树后追加 '> {note}'。根标题由 export_markdown 负责。"""
    ...

def export_markdown(doc):
    """doc 为 get_doc() 返回的 data 层 {"node": {...}}。
    首行 '# 标题'，其余递归为 '- ' 列表。结构无效时抛 MubuError。"""
    ...

def markdown_to_doc(md):
    """Markdown 文本 → {"node": {"id": "root", "text": ..., "children": [...]}}。
    标题为顶层节点；多标题时首个为 root，其余作为 root 的 children；
    列表项用栈按缩进深度维护层级；'- [ ]'/'- [x]' 设 checked；
    '> ' 作为对应层级节点的 note。"""
    ...
```

导出示例（幕布 → Markdown）：

```
# 读书笔记
- 第一章
  - [x] 读完
  - [ ] 写笔记
> 第一章的备注
```

> 说明：根节点的 `text` 渲染为 `# 标题`，其直接子节点从缩进 0 的 `- ` 列表开始；
> note 出现在其所属节点（含子树）之后，并按缩进深度归属到对应节点。

---

## 命令参考（CLI）

| 命令 | 说明 |
|------|------|
| `login` | 手机号密码登录，Token 本地缓存 |
| `list --folder <id>` | 获取文件夹下的文档/子文件夹列表（`--json` 输出原始 JSON） |
| `mkdir <name> --parent <id>` | 创建文件夹 |
| `create <name> --folder <id> [--content <json>] [--md <file>]` | 创建文档；`--md` 从 Markdown 文件导入 |
| `get <doc_id> [--export markdown\|json]` | 获取文档；`--export markdown` 输出真实 Markdown |
| `save <doc_id> [--file <f>] [--md <file>] [--content <c>]` | 保存文档；`--md` 从 Markdown 文件导入 |
| `delete <id> [--type doc\|folder] --yes` | 删除文档或文件夹（⚠️ 不可逆；`--type` 默认 folder，必须显式 `--yes` 才执行）|
| `move <item_id> --target <folder_id>` | 移动文档到其他文件夹（⚠️ 该端点**尚未经真机验证**，可能返回 illegal request，慎用） |
| `search <关键字> [--max-depth N] [--limit N]` | 按名称本地搜索文档/文件夹（递归遍历，大小写不敏感） |
| `export-tree --folder <id> [--output <dir>] [--max-depth N]` | 递归导出整个文件夹树为嵌套 Markdown 文件 |
| `rename <id> --name <新名> [--type doc\|folder]` | 重命名文档（`save_doc` name）或文件夹（已验证端点 `/list/rename_folder`，`folderId` 填自身 id）|
| `opml <doc_id> [--format opml\|freeplane]` | 导出为 OPML 2.0 / FreeMind XML（兼容 XMind 等其它大纲工具）|

Markdown 往返示例：

```bash
# 导出为 Markdown
python3 scripts/mubu_api.py get <doc_id> --export markdown

# 从 Markdown 创建文档
python3 scripts/mubu_api.py create "我的文档" --folder <folder_id> --md ./outline.md

# 从 Markdown 更新文档
python3 scripts/mubu_api.py save <doc_id> --md ./outline.md

# 移动文档
python3 scripts/mubu_api.py move <doc_id> --target <folder_id>

# 按名称本地搜索文档/文件夹（递归遍历所有子文件夹，大小写不敏感）
python3 scripts/mubu_api.py search "项目"
python3 scripts/mubu_api.py search "项目" --json

# 递归导出整个文件夹树为嵌套 Markdown
python3 scripts/mubu_api.py export-tree --folder <root_folder_id> --output ./backup

# 重命名文档 / 文件夹
python3 scripts/mubu_api.py rename <doc_id> --name "新标题" --type doc
python3 scripts/mubu_api.py rename <folder_id> --name "新文件夹名" --type folder

# 导出为 OPML / FreeMind
python3 scripts/mubu_api.py opml <doc_id> --format opml
python3 scripts/mubu_api.py opml <doc_id> --format freeplane
```

---

## Token 刷新策略

- access_token 有效期约 2 小时，本地以 `expires_at` 缓存于 `~/.mubu_token`。
- 每次请求发起前调用 `ensure_valid_token()`：若未持有 token，或距过期不足
  `300 + 60`（leeway）秒，则使用缓存的 `phone`/`password` **重新登录**获取新 token。
- **刷新不依赖 refresh_token**（M1 未启用）。
- **鉴权失败仅重试 1 次**：`_request` 捕获 401 / 登录失效类错误后重新登录并重试最多一次；
  第二次仍失败则抛出 `MubuError`，**不再重登**，避免密码错误/账号封禁场景下的死循环。
- 403（权限不足）或其它非 0 业务 code **不触发重登**。
- Token 写入采用原子写（先写 `.tmp` 再 `os.rename`），写完追加 `os.chmod(TOKEN_FILE, 0o600)`，
  确保 Token 文件仅属主可读写（M2 的 T5 已实现）。

---

## 配置说明

脚本通过环境变量读取凭据（优先级：环境变量 > `~/.workbuddy/.env.mubu` 文件；
两者皆无时，`login` 子命令会交互式提示输入，绝不接受明文命令行参数）：

```bash
export MUBU_PHONE="你的手机号"
export MUBU_PASSWORD="你的密码"
```

也可在 `~/.workbuddy/.env.mubu` 中配置（由 Skill 宿主加载为环境变量，且仅属主可读写）：

```
MUBU_PHONE=你的手机号
MUBU_PASSWORD=你的密码
```

---

## 已知限制（M1）

- `expand`（幕布大纲的折叠/展开状态）不在本期往返范围内，导入后节点默认展开。
- 有序列表 `1.` 不被解析，仅支持无序列表 `- `。
- 图片 / 附件类型节点不在本期 Markdown 往返范围内（会丢失媒体内容）。
- 多个顶层标题导入时，首个为 root，其余作为 root 的 children；其后的列表项统一挂在
  root 下（规范未要求按标题再嵌套）。

---

## 注意事项

1. **非官方 API**: 幕布未提供官方开放平台，此 Skill 基于逆向分析实现
2. **稳定性**: API 可能随版本更新而变化，如遇问题请反馈
3. **频率限制**: 请勿频繁调用，避免触发限流
4. **数据安全**: Token 存储在本地，请勿泄露

---

## Agent 使用指引

当用户提到幕布、mubu 相关操作（如登录、文档/文件夹管理、大纲导入导出）时，使用本 Skill 的脚本完成操作。

### 前置检查

1. 确认系统已安装 Python 3 和 requests 库：
   ```bash
   python3 -c "import requests; print('OK')"
   ```
   如果缺少 requests：`pip3 install requests`

2. 确认环境变量已配置：
   - `MUBU_PHONE` — 幕布手机号
   - `MUBU_PASSWORD` — 幕布密码
   - 如未配置，需提示用户先设置

### 脚本路径

```
~/.workbuddy/skills/mubu-integration/scripts/mubu_api.py
```

### 常用命令速查

| 用户意图 | 执行命令 |
|---------|---------|
| 登录幕布 | `python3 scripts/mubu_api.py login` |
| 查看文档列表 | `python3 scripts/mubu_api.py list` |
| 查看某文件夹 | `python3 scripts/mubu_api.py list --folder <folder_id>` |
| 创建文件夹 | `python3 scripts/mubu_api.py mkdir "文件夹名"` |
| 创建文档 | `python3 scripts/mubu_api.py create "文档名" --folder <folder_id>` |
| 从 Markdown 创建文档 | `python3 scripts/mubu_api.py create "文档名" --folder <folder_id> --md outline.md` |
| 获取文档内容 | `python3 scripts/mubu_api.py get <doc_id>` |
| 导出为 Markdown | `python3 scripts/mubu_api.py get <doc_id> --export markdown` |
| 从 Markdown 保存文档 | `python3 scripts/mubu_api.py save <doc_id> --md outline.md` |
| 从文件保存文档 | `python3 scripts/mubu_api.py save <doc_id> --file content.json` |
| 移动文档 | `python3 scripts/mubu_api.py move <doc_id> --target <folder_id>` |
| 删除文档/文件夹 | `python3 scripts/mubu_api.py delete <id> --type doc\|folder --yes`（⚠️ 删除不可逆，必须显式 `--yes`；`--type` 默认 folder）|
| 按名称搜索 | `python3 scripts/mubu_api.py search <关键字> [--max-depth N] [--limit N]` |
| 按名称搜索（JSON） | `python3 scripts/mubu_api.py search <关键字> [--max-depth N] [--limit N] --json` |

### 典型工作流

**场景 1：用户说"把这份大纲同步到幕布"**
1. 确认内容来源（文件或对话中直接提供）
2. 如果是 Markdown，直接用脚本创建文档并导入
3. 返回新文档 ID 和链接

**场景 2：用户说"导出我的幕布笔记"**
1. 先列出文档列表让用户选择，或按名称搜索
2. 获取文档内容
3. 转换为 Markdown 格式返回

**场景 3：用户说"在幕布建一个项目文件夹"**
1. 确认文件夹名称和层级结构
2. 批量创建文件夹
3. 返回创建结果

---

## 工作流示例

### 示例 1: 从 Markdown 创建幕布文档

```
用户: 把这份 Markdown 大纲同步到幕布
```

执行步骤：
1. 解析 Markdown 结构
2. 转换为幕布 JSON 格式
3. 登录获取 Token
4. 创建文档并保存内容

### 示例 2: 导出幕布文档为 Markdown

```
用户: 导出我的"读书笔记"文档
```

执行步骤：
1. 登录获取 Token
2. 本地搜索匹配文档：`python3 scripts/mubu_api.py search "读书笔记"`
3. 获取文档内容
4. 转换为 Markdown 并返回

### 示例 3: 批量创建文件夹结构

```
用户: 在幕布创建项目文档结构：需求分析、设计文档、开发日志、测试报告
```

执行步骤：
1. 登录获取 Token
2. 创建项目文件夹
3. 批量创建子文件夹
4. 返回创建结果
