"""mubu 包 — 文档结构 ↔ Markdown / OPML / FreeMind 转换与展示格式化。

M1（P0）阶段新增能力：
- Markdown 导出：doc_to_markdown / export_markdown
- Markdown 导入：markdown_to_doc

Roadmap 阶段新增能力：
- OPML / FreeMind 导出：doc_to_opml / doc_to_freeplane
- 文件名安全化处理：_safe_filename
- 列表 / 搜索结果展示格式化：format_list / format_search
"""

import re
from typing import Dict, Any, List

from mubu.config import MubuError


def doc_to_markdown(node: Dict[str, Any], level: int = 0) -> str:
    """将节点（及其子树）递归渲染为 Markdown 列表片段。

    子节点使用 '- ' 列表项，缩进 = 2 * level；含 checked 渲染为 '- [x]'/'- [ ]'；
    含 note 在其子树之后追加 '> {note}'。根标题（'# '）由 export_markdown 负责。

    Args:
        node: 节点字典，可包含 text / checked / note / children
        level: 当前节点深度（根节点的直接子节点为 0）

    Returns:
        Markdown 列表片段（不含根标题行）
    """
    lines: List[str] = []
    text = (node.get("text") or "").replace("\n", " ")
    indent = " " * (2 * level)

    # 勾选状态：兼容旧版 checked 与真实 API 的 finish（布尔）
    if node.get("checked") is not None or node.get("finish") is not None:
        mark = "x" if (node.get("checked") or node.get("finish")) else " "
        lines.append(f"{indent}- [{mark}] {text}")
    else:
        lines.append(f"{indent}- {text}")

    # 递归子节点（位于 note 之前）
    for child in node.get("children") or []:
        lines.append(doc_to_markdown(child, level + 1))

    # 备注：节点（含其子树）之后追加
    note = node.get("note")
    if note:
        lines.append(f"{indent}> {note}")

    return "\n".join(lines)


def export_markdown(doc: Dict[str, Any]) -> str:
    """将文档结构转换为 Markdown 文本。

    兼容两种输入形状（get_doc 修复后引入真实 API 形状，需向后兼容旧往返形状）：
    - 真实 API（get_doc 修复后返回）：{"name":..., "nodes":[顶层节点...]}
      mubu 文档通常只有一个顶层节点，其 text 即文档标题，children 为大纲正文。
    - 本地往返（markdown_to_doc 返回）：{"node":{...}} 或裸 {"text":..., "children":[...]}

    Args:
        doc: 文档结构（见上两种形状）

    Returns:
        Markdown 文本（首行为 '# 标题'）

    Raises:
        MubuError: 文档结构无效（既无有效 text 也无 children）时
    """
    # 新形状：真实 API 的 nodes 顶层数组（优先）
    nodes = doc.get("nodes")
    if nodes:
        lines: List[str] = []
        for node in nodes:
            title = (node.get("text") or "").replace("\n", " ")
            lines.append(f"# {title}")
            for child in node.get("children") or []:
                lines.append(doc_to_markdown(child, level=0))
            note = node.get("note")
            if note:
                lines.append(f"> {note}")
        return "\n".join(lines)

    # 旧形状：markdown_to_doc 的单一 node（或裸 node）
    root = doc.get("node") or doc
    if not isinstance(root, dict) or (not root.get("text") and not root.get("children")):
        raise MubuError("无效的文档结构")

    title = (root.get("text") or "").replace("\n", " ")
    lines = [f"# {title}"]
    for child in root.get("children") or []:
        lines.append(doc_to_markdown(child, level=0))
    # 根节点的 note（备注）在 children 之后输出
    note = root.get("note")
    if note:
        lines.append(f"> {note}")
    return "\n".join(lines)


def _safe_filename(name: str) -> str:
    """将文档/文件夹名称转为安全的文件名（去除路径非法字符）。"""
    bad = ['/', ':', '*', '?', '"', '<', '>', '|', chr(92)]
    cleaned = ''.join('_' if ch in bad else ch for ch in name).strip()
    return cleaned or 'untitled'


def doc_to_opml(doc: Dict[str, Any]) -> str:
    """将幕布文档转为 OPML 2.0 XML（兼容 FreeMind / XMind 等大纲工具导入）。"""
    import xml.etree.ElementTree as ET

    root = doc.get("node") or doc
    title = (root.get("text") or "mubu-export").replace("\\n", " ")

    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(opml, "body")

    def build(node: Dict[str, Any], parent: ET.Element) -> None:
        text = (node.get("text") or "").replace("\\n", " ")
        outline = ET.SubElement(parent, "outline", text=text)
        note = node.get("note")
        if note:
            outline.set("_note", note)
        for child in node.get("children") or []:
            build(child, outline)

    build(root, body)
    ET.indent(opml, space="  ")
    return ET.tostring(opml, encoding="utf-8", xml_declaration=True).decode("utf-8")


def doc_to_freeplane(doc: Dict[str, Any]) -> str:
    """将幕布文档转为 FreeMind (Freeplane) XML。"""
    import xml.etree.ElementTree as ET

    root = doc.get("node") or doc
    title = (root.get("text") or "mubu-export").replace("\\n", " ")

    mindmap = ET.Element("map", version="1.0.1")
    root_node = ET.SubElement(mindmap, "node", text=title)

    def build(node: Dict[str, Any], parent: ET.Element) -> None:
        for child in node.get("children") or []:
            text = (child.get("text") or "").replace("\\n", " ")
            node_el = ET.SubElement(parent, "node", text=text)
            note = child.get("note")
            if note:
                note_el = ET.SubElement(node_el, "richcontent", type="note")
                ET.SubElement(note_el, "html").text = note
            build(child, node_el)

    build(root, root_node)
    ET.indent(mindmap, space="  ")
    return ET.tostring(mindmap, encoding="utf-8", xml_declaration=True).decode("utf-8")


def markdown_to_doc(md: str) -> Dict[str, Any]:
    r"""将 Markdown 文本解析为幕布文档结构。

    解析规则（按行）：
    - 标题 '^#+\s+(.*)' → 顶层节点；多个顶层标题时第一个为 root，其余作为 root 的 children
    - 无序列表 '^(\s*)-\s+(.*)' → 子节点；前导空格数 // 2 = 相对深度，用栈维护 (depth → node)
    - 勾选 '- [ ]'/'- [x]' → 设 checked
    - 引用 '^(\s*)>\s+(.*)' → 作为上一层级节点的 note（按缩进深度归属）
    - 纯文本无列表 → 整个作为单节点正文

    Returns:
        {"node": {"id": "root", "text": ..., "children": [...]}}
    """
    root_node: Dict[str, Any] = {"id": "root", "text": "", "children": []}
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"node_{counter[0]}"

    lines = md.split("\n")

    # 收集所有标题行
    headings: List[str] = []
    for line in lines:
        if not line.strip():
            continue
        m = re.match(r"^#+\s+(.*)$", line)
        if m:
            headings.append(m.group(1).strip())

    # 是否存在列表项
    has_list = any(
        re.match(r"^\s*-\s+", line) for line in lines if line.strip()
    )

    # 纯文本（无标题且无列表）
    if not headings and not has_list:
        text = md.strip()
        if text:
            root_node["text"] = text
        return {"node": root_node}

    # 设置 root 文本，其余标题作为 root 的 children
    if headings:
        root_node["text"] = headings[0]
        for h in headings[1:]:
            root_node["children"].append({"id": next_id(), "text": h, "children": []})

    if not has_list:
        return {"node": root_node}

    # 用栈维护 (depth, node)；栈底为 root
    stack: List[Any] = [(0, root_node)]

    for line in lines:
        if not line.strip():
            continue

        # 标题行已处理（root 文本 / children），跳过
        if re.match(r"^#+\s+", line):
            continue

        # 引用 → 作为对应层级节点的 note
        m_note = re.match(r"^(\s*)>\s+(.*)$", line)
        if m_note:
            note_depth = len(m_note.group(1)) // 2
            note_text = m_note.group(2).strip()
            target = root_node
            for d, n in reversed(stack):
                if d == note_depth:
                    target = n
                    break
            target["note"] = note_text
            continue

        # 无序列表项
        m_list = re.match(r"^(\s*)-\s+(.*)$", line)
        if m_list:
            indent = len(m_list.group(1))
            depth = indent // 2
            content = m_list.group(2).strip()

            # 勾选状态
            checked: Any = None
            mc = re.match(r"^\[([ xX])\]\s+(.*)$", content)
            if mc:
                checked = mc.group(1).lower() == "x"
                content = mc.group(2).strip()

            node: Dict[str, Any] = {"id": next_id(), "text": content, "children": []}
            if checked is not None:
                node["checked"] = checked

            # 弹出比当前深度更深或相等的节点，找到父节点
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent = stack[-1][1] if stack else root_node
            parent.setdefault("children", []).append(node)
            stack.append((depth, node))
            continue

    return {"node": root_node}


def format_list(data: Dict) -> str:
    """格式化文档列表为可读文本。

    真机 get_list 返回文档列表字段为 ``documents``；旧版/个别环境可能用 ``docs``，
    此处优先读 ``documents`` 并兜底 ``docs``，避免真机上读不到文档。
    """
    lines = []
    folders = data.get("folders", []) or []
    docs = data.get("documents") or data.get("docs") or []

    if folders:
        lines.append("📁 文件夹:")
        for f in folders:
            name = f.get("name", "未命名")
            fid = f.get("id", "")
            lines.append(f"  [{fid}] {name}")

    if docs:
        lines.append("\n📄 文档:")
        for d in docs:
            name = d.get("name", "未命名")
            did = d.get("id", "")
            lines.append(f"  [{did}] {name}")

    if not folders and not docs:
        lines.append("（空）")

    return "\n".join(lines)


def format_search(results: List[Dict]) -> str:
    """格式化搜索结果为可读文本，复用 format_list 的分区展示风格（T6）。

    将匹配项分为 📁 文件夹 / 📄 文档 两区，命中项附带路径（path）便于定位。
    """
    folders = [r for r in results if r.get("type") == "folder"]
    docs = [r for r in results if r.get("type") == "doc"]
    lines = []

    if folders:
        lines.append("📁 文件夹:")
        for f in folders:
            path = f.get("path", "")
            suffix = f"  ({path})" if path else ""
            lines.append(f"  [{f.get('id')}] {f.get('name')}{suffix}")

    if docs:
        lines.append("\n📄 文档:")
        for d in docs:
            path = d.get("path", "")
            suffix = f"  ({path})" if path else ""
            lines.append(f"  [{d.get('id')}] {d.get('name')}{suffix}")

    if not folders and not docs:
        lines.append("（无匹配结果）")

    return "\n".join(lines)
