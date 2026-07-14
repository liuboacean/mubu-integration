# Contributing

欢迎贡献！

## 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

## 开发环境

```bash
# 克隆仓库
git clone https://github.com/liuboacean/mubu-integration.git
cd mubu-integration

# 安装依赖（运行时 + 测试；开发依赖在 requirements-dev.txt）
pip install -r requirements.txt -r requirements-dev.txt

# 运行全部测试（共 84 个 pytest 用例）
PYTHONPATH=scripts python -m pytest -v

# 脚本运行入口
python3 scripts/mubu_api.py --help
```

## 行为准则

- 尊重所有贡献者
- 建设性讨论
- 专注于对项目最有利的事情
