# mubu-integration

[![GitHub stars](https://img.shields.io/github/stars/liuboacean/mubu-integration?style=social)](https://github.com/liuboacean/mubu-integration/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/liuboacean/mubu-integration?style=social)](https://github.com/liuboacean/mubu-integration/network/members)
[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


幕布（Mubu）集成 Skill，支持通过命令行管理幕布文档和文件夹。

## 功能

- 🔐 登录认证（手机号 + 密码，Token 本地缓存）
- 📁 文件夹管理（创建、列表、删除、移动）
- 📄 文档管理（创建、获取、保存、删除）
- 📋 大纲导出（Markdown 格式）

## 安装

```bash
npx skills add liuboacean/mubu-integration
```

## 配置

设置环境变量：

```bash
export MUBU_PHONE="你的手机号"
export MUBU_PASSWORD="你的密码"
```

或在 `~/.workbuddy/.env.mubu` 文件中配置：

```
MUBU_PHONE=你的手机号
MUBU_PASSWORD=你的密码
```

## 使用

### 命令行

```bash
# 登录
python3 scripts/mubu_api.py login

# 获取根目录列表
python3 scripts/mubu_api.py list

# 获取子文件夹内容
python3 scripts/mubu_api.py list --folder <folder_id>

# 创建文件夹
python3 scripts/mubu_api.py mkdir "新文件夹"

# 创建文档
python3 scripts/mubu_api.py create "新文档" --folder <folder_id>

# 从 Markdown 文件导入创建文档
python3 scripts/mubu_api.py create "新文档" --folder <folder_id> --md outline.md

# 获取文档内容（JSON）
python3 scripts/mubu_api.py get <doc_id>

# 导出为 Markdown（真实往返，非占位）
python3 scripts/mubu_api.py get <doc_id> --export markdown

# 保存文档
python3 scripts/mubu_api.py save <doc_id> --content "内容"
python3 scripts/mubu_api.py save <doc_id> --file content.md

# 从 Markdown 文件导入更新文档
python3 scripts/mubu_api.py save <doc_id> --md outline.md

# 移动文档到其他文件夹
python3 scripts/mubu_api.py move <doc_id> --target <folder_id>

# 删除
python3 scripts/mubu_api.py delete <id>

# 按名称本地搜索文档/文件夹（递归遍历所有子文件夹，大小写不敏感）
python3 scripts/mubu_api.py search "项目"
python3 scripts/mubu_api.py search "项目" --json
```

### Agent 触发词

幕布、mubu、大纲笔记、思维导图导出、幕布同步

## 注意

基于幕布 Web API 逆向实现，非官方接口，可能随幕布版本更新而变化。

### Token 刷新策略

- access_token 约 2 小时过期，临近过期自动重新登录（使用缓存凭据，不依赖 refresh_token）。
- 鉴权失败仅重试 1 次，避免密码错误/账号封禁时陷入死循环。
- 403 权限不足等其它错误不触发重登。

### 已知限制（M1/M2）

- 大纲折叠状态 `expand`、有序列表 `1.`、图片/附件节点不在本期 Markdown 往返范围。
- 多个顶层标题导入时，首个为根，其余作为根的子节点。
- `search` 为本地过滤：从根文件夹递归遍历所有子文件夹按名称匹配（大小写不敏感），
  幕布无公开 `/search` 端点，故依赖本地遍历，文件夹极多时可能稍慢。

## License

MIT
