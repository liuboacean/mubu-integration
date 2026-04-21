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

# 获取文档内容
python3 scripts/mubu_api.py get <doc_id>

# 保存文档
python3 scripts/mubu_api.py save <doc_id> --content "内容"
python3 scripts/mubu_api.py save <doc_id> --file content.md

# 删除
python3 scripts/mubu_api.py delete <id>
```

### Agent 触发词

幕布、mubu、大纲笔记、思维导图导出、幕布同步

## 注意

基于幕布 Web API 逆向实现，非官方接口，可能随幕布版本更新而变化。

## License

MIT
