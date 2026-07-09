---
name: mubu-integration
description: 幕布笔记集成，支持登录认证、文档管理、文件夹操作、大纲导出等功能。触发词：幕布、mubu、大纲笔记、思维导图导出、幕布同步
---

# 幕布集成 Skill

幕布（mubu.com）是一款极简大纲笔记工具，支持一键生成思维导图。本 Skill 提供 API 集成能力。

## 功能概览

| 功能 | 接口 | 说明 |
|------|------|------|
| 用户登录 | `POST /user/phone_login` | 手机号密码登录获取 Token |
| Token 刷新 | 自动处理 | access_token 2小时过期，临近过期自动重新登录（重登仅重试 1 次，杜绝死循环） |
| 创建文件夹 | `POST /list/create_folder` | 在指定位置创建文件夹 |
| 创建文档 | `POST /list/create_doc` | 创建新的大纲文档 |
| 获取列表 | `POST /list/get` | 获取文件夹下的文档列表 |
| 获取文档 | `POST /doc/get` | 获取文档详细内容 |
| 更新文档 | `POST /doc/save` | 保存/更新文档内容 |
| 删除文档 | `POST /list/delete` | 删除文档或文件夹 |
| 移动文档 | `POST /list/move` | 移动文档到其他文件夹 |
| 导出 Markdown | 本地转换 | 将大纲结构转换为 Markdown |

## API 基础信息

- **Base URL**: `https://api2.mubu.com/v3/api`
- **认证方式**: JWT Token，通过请求头 `jwt-token` 传递
- **Content-Type**: `application/json;charset=UTF-8`

## 环境变量配置

在使用前，需要配置以下环境变量：

```bash
export MUBU_PHONE="your_phone_number"    # 幕布账号手机号
export MUBU_PASSWORD="your_password"      # 幕布账号密码
```

或者直接在脚本中配置。

---

## 使用说明

### 1. 认证流程

```python
import requests
import json

def login(phone, password):
    """幕布登录获取 Token"""
    url = "https://api2.mubu.com/v3/api/user/phone_login"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    data = {
        "phone": phone,
        "password": password,
        "callbackType": 0
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get("code") == 0:
        return {
            "token": result["data"]["token"],
            "user_id": result["data"]["user"]["id"],
            "username": result["data"]["user"]["name"]
        }
    else:
        raise Exception(f"登录失败: {result.get('msg')}")
```

### 2. 创建文件夹

```python
def create_folder(token, name, parent_id="0"):
    """创建文件夹
    
    Args:
        token: JWT Token
        name: 文件夹名称
        parent_id: 父文件夹ID，根目录为 "0"
    
    Returns:
        新创建的文件夹ID
    """
    url = "https://api2.mubu.com/v3/api/list/create_folder"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    data = {
        "folderId": parent_id,
        "name": name
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get("code") == 0:
        return result["data"]["folder"]["id"]
    else:
        raise Exception(f"创建文件夹失败: {result.get('msg')}")
```

### 3. 创建文档

```python
def create_doc(token, name, folder_id="0", content=""):
    """创建文档
    
    Args:
        token: JWT Token
        name: 文档名称
        folder_id: 所在文件夹ID，根目录为 "0"
        content: 文档初始内容（大纲结构）
    
    Returns:
        新创建的文档ID
    """
    url = "https://api2.mubu.com/v3/api/list/create_doc"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    data = {
        "folderId": folder_id,
        "name": name,
        "content": content
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get("code") == 0:
        return result["data"]["doc"]["id"]
    else:
        raise Exception(f"创建文档失败: {result.get('msg')}")
```

### 4. 获取文档列表

```python
def get_list(token, folder_id="0"):
    """获取文件夹下的文档列表
    
    Args:
        token: JWT Token
        folder_id: 文件夹ID，根目录为 "0"
    
    Returns:
        文档和文件夹列表
    """
    url = "https://api2.mubu.com/v3/api/list/get"
    headers = {
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    response = requests.post(url, headers=headers, json={"folderId": folder_id})
    result = response.json()
    if result.get("code") == 0:
        return result["data"]
    else:
        raise Exception(f"获取列表失败: {result.get('msg')}")
```

### 5. 获取文档内容

```python
def get_doc(token, doc_id):
    """获取文档详细内容
    
    Args:
        token: JWT Token
        doc_id: 文档ID
    
    Returns:
        文档详细内容（包含大纲结构）
    """
    url = "https://api2.mubu.com/v3/api/doc/get"
    headers = {
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    response = requests.post(url, headers=headers, json={"id": doc_id})
    result = response.json()
    if result.get("code") == 0:
        return result["data"]
    else:
        raise Exception(f"获取文档失败: {result.get('msg')}")
```

### 6. 保存文档

```python
def save_doc(token, doc_id, content, name=None):
    """保存/更新文档内容
    
    Args:
        token: JWT Token
        doc_id: 文档ID
        content: 文档内容（JSON格式的大纲结构）
        name: 可选，更新文档名称
    """
    url = "https://api2.mubu.com/v3/api/doc/save"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    data = {
        "id": doc_id,
        "content": content
    }
    if name:
        data["name"] = name
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get("code") != 0:
        raise Exception(f"保存文档失败: {result.get('msg')}")
```

### 7. 删除文档/文件夹

```python
def delete_item(token, item_id):
    """删除文档或文件夹
    
    Args:
        token: JWT Token
        item_id: 文档或文件夹ID
    """
    url = "https://api2.mubu.com/v3/api/list/delete"
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    data = {"id": item_id}
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get("code") != 0:
        raise Exception(f"删除失败: {result.get('msg')}")
```

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

由于幕布的 Token 有效期限制（access_token 2小时，refresh_token 30天），建议：

1. **本地缓存**: 将 Token 保存到本地文件（如 `~/.mubu_token`）
2. **自动刷新**: 在 Token 快过期时自动刷新
3. **错误重试**: 遇到 401 错误时重新登录

```python
import os
import time
import json

TOKEN_FILE = os.path.expanduser("~/.mubu_token")

def save_token(token_data):
    """保存 Token 到本地"""
    token_data["expires_at"] = time.time() + 7200  # 2小时后过期
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

def load_token():
    """从本地加载 Token"""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None

def is_token_valid(token_data):
    """检查 Token 是否有效"""
    if not token_data:
        return False
    return time.time() < token_data.get("expires_at", 0)
```

---

## 导出 / 导入 Markdown

M1 已落地真正的 Markdown 往返（不再是占位）。核心纯函数位于 `scripts/mubu_api.py`：

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
| `delete <id>` | 删除文档或文件夹 |
| `move <item_id> --target <folder_id>` | 移动文档到其他文件夹 |

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

脚本通过环境变量读取凭据（优先级：命令行参数 > 环境变量）：

```bash
export MUBU_PHONE="你的手机号"
export MUBU_PASSWORD="你的密码"
```

也可在 `~/.workbuddy/.env.mubu` 中配置（由 Skill 宿主加载为环境变量）：

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

当用户提到幕布、mubu、大纲笔记相关操作时，使用本 Skill 的脚本完成操作。

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
| 删除文档 | `python3 scripts/mubu_api.py delete <id>` |
| 按名称搜索 | `python3 scripts/mubu_api.py search <关键字>` |
| 按名称搜索（JSON） | `python3 scripts/mubu_api.py search <关键字> --json` |

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
