"""mubu 包 — 幕布 API 封装（模块化拆分后的正式包）。

子模块职责：
- config: 常量 / 配置 / 日志 / 异常 / 路径安全
- convert: 文档结构 ↔ Markdown / OPML / FreeMind 转换 + 展示格式化
- client: MubuClient（鉴权 / 请求 / 文档·文件夹·搜索·导出）
- cli: 命令行入口（argparse 子命令 + 日志配置）

旧入口 scripts/mubu_api.py 现为向后兼容 shim，重新导出本包全部公开符号。
"""

__version__ = "1.3.4"
