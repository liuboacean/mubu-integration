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
| Token 刷新 | 自动处理 | access_token 2小时过期，refresh_token 30天 |
| 创建文件夹 | `POST /list/create_folder` | 在指定位置创建文件夹 |
| 创建文档 | `POST /list/create_doc` | 创建新的大纲文档 |
| 获取列表 | `GET /list/list` | 获取文件夹下的文档列表 |
| 获取文档 | `GET /doc/get` | 获取文档详细内容 |
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
    url = f"https://api2.mubu.com/v3/api/list/list?folderId={folder_id}"
    headers = {
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    response = requests.get(url, headers=headers)
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
    url = f"https://api2.mubu.com/v3/api/doc/get?id={doc_id}"
    headers = {
        "jwt-token": token,
        "Origin": "https://mubu.com",
        "Referer": "https://mubu.com/"
    }
    response = requests.get(url, headers=headers)
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

## 导出 Markdown

将幕布大纲转换为 Markdown 格式：

```python
def node_to_markdown(node, level=0):
    """将幕布节点转换为 Markdown"""
    lines = []
    indent = "  " * level
    bullet = "- " if level > 0 else ""
    lines.append(f"{indent}{bullet}{node['text']}")
    
    for child in node.get("children", []):
        lines.extend(node_to_markdown(child, level + 1))
    
    return lines

def export_markdown(doc_data):
    """导出文档为 Markdown"""
    root = doc_data.get("node", {})
    lines = node_to_markdown(root)
    return "\n".join(lines)
```

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
| 获取文档内容 | `python3 scripts/mubu_api.py get <doc_id>` |
| 导出为 Markdown | `python3 scripts/mubu_api.py get <doc_id> --export markdown` |
| 从文件保存文档 | `python3 scripts/mubu_api.py save <doc_id> --file content.md` |
| 删除文档 | `python3 scripts/mubu_api.py delete <id>` |

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
2. 搜索文档
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
