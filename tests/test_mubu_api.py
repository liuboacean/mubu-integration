#!/usr/bin/env python3
"""M1 (P0) 核心测试：Markdown 往返 / 401 重试 / 原子写 / CLI 注册。

框架：responses + unittest.mock + pytest
覆盖：
  1. roundtrip（md→doc→md, doc→md→doc，多层嵌套+note+checked 混合）
  2. doc_to_markdown / export_markdown 单元
  3. markdown_to_doc 单元
  4. 401 仅重试 1 次（含 403 不重试）
  5. _save_token 原子写
  6. CLI 子命令解析
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from unittest import mock

import requests
import responses
from responses import matchers
import pytest

# 让 scripts/mubu_api.py 可被导入
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mubu_api
from mubu_api import (
    MubuClient,
    MubuError,
    doc_to_markdown,
    export_markdown,
    markdown_to_doc,
)

BASE_URL = mubu_api.BASE_URL


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _norm_md(s: str) -> str:
    """规范化 Markdown：去首尾空白，每行去尾部空白。"""
    return "\n".join(line.rstrip() for line in s.strip().split("\n"))


def _node_eq(a: dict, b: dict) -> bool:
    """递归比较节点树（忽略 id 字段，因导入时 id 会自增重建）。"""
    if (a.get("text") or "") != (b.get("text") or ""):
        return False
    if a.get("checked") != b.get("checked"):
        return False
    if (a.get("note") or None) != (b.get("note") or None):
        return False
    ac = a.get("children") or []
    bc = b.get("children") or []
    if len(ac) != len(bc):
        return False
    return all(_node_eq(x, y) for x, y in zip(ac, bc))


@pytest.fixture
def isolated_client(tmp_path):
    """构造一个 token 文件被隔离、且持有有效 token 的客户端。"""
    tok = tmp_path / "tok.json"
    with mock.patch.object(mubu_api, "TOKEN_FILE", tok):
        c = MubuClient(phone="p", password="w")
        c.token = "valid-token"
        c.expires_at = time.time() + 3600  # 远未过期，ensure_valid_token 不应重登
        yield c


# --------------------------------------------------------------------------- #
# 1. roundtrip（核心价值）
# --------------------------------------------------------------------------- #
class TestRoundtrip:
    def test_md_to_doc_to_md_nested(self):
        md = (
            "# 项目计划\n"
            "- 阶段一\n"
            "  - [x] 需求评审\n"
            "  - [ ] 技术方案\n"
            "    - 架构设计\n"
            "    - 接口定义\n"
            "> 阶段一的备注\n"
            "- 阶段二\n"
            "  - 测试\n"
        )
        doc = markdown_to_doc(md)
        md2 = export_markdown(doc)
        assert _norm_md(md2) == _norm_md(md)

    def test_doc_to_md_to_doc_nested(self):
        doc = {
            "node": {
                "id": "root",
                "text": "项目计划",
                "children": [
                    {
                        "id": "a",
                        "text": "阶段一",
                        "children": [
                            {"id": "a1", "text": "需求评审", "checked": True},
                            {
                                "id": "a2",
                                "text": "技术方案",
                                "checked": False,
                                "children": [
                                    {"id": "a2a", "text": "架构设计"},
                                    {"id": "a2b", "text": "接口定义"},
                                ],
                            },
                        ],
                        "note": "阶段一的备注",
                    },
                    {
                        "id": "b",
                        "text": "阶段二",
                        "children": [{"id": "b1", "text": "测试"}],
                    },
                ],
            }
        }
        md = export_markdown(doc)
        doc2 = markdown_to_doc(md)
        assert _node_eq(doc["node"], doc2["node"])

    def test_roundtrip_simple_checked(self):
        md = "# 读书笔记\n- 第一章\n  - [x] 读完\n  - [ ] 写笔记\n> 第一章的备注\n"
        doc = markdown_to_doc(md)
        md2 = export_markdown(doc)
        assert _norm_md(md2) == _norm_md(md)

    def test_roundtrip_plain_text(self):
        md = "只是一段纯文本，没有标题也没有列表"
        doc = markdown_to_doc(md)
        assert doc["node"]["text"] == md
        # 导出纯文本（无标题）→ 仅 '# ' 行，结构稳定
        assert export_markdown(doc).startswith("# ")


# --------------------------------------------------------------------------- #
# 2. doc_to_markdown / export_markdown 单元
# --------------------------------------------------------------------------- #
class TestExportMarkdownRootNote:
    """export_markdown 应输出根节点的 note（Bug 修复回归）"""

    def test_root_note_appears_after_children(self):
        """根节点 note 在 children 之后输出"""
        doc = {
            "node": {
                "id": "root",
                "text": "文档标题",
                "note": "这是根节点的备注",
                "children": [
                    {"id": "c1", "text": "子节点1"},
                    {"id": "c2", "text": "子节点2", "checked": True},
                ],
            }
        }
        result = export_markdown(doc)
        assert "# 文档标题" in result
        assert "- 子节点1" in result
        assert "- [x] 子节点2" in result
        assert "> 这是根节点的备注" in result
        # 根 note 应在 children 之后
        assert result.index("> 这是根节点的备注") > result.index("- [x] 子节点2")

    def test_root_note_empty_omitted(self):
        """根节点无 note 时不输出 > 行"""
        doc = {"node": {"id": "root", "text": "标题"}}
        result = export_markdown(doc)
        assert result == "# 标题"
        assert "> " not in result

    def test_root_note_roundtrip_consistency(self):
        """含根 note 的文档应能完整往返"""
        md = (
            "# 项目计划\n"
            "- 阶段一\n"
            "  - [x] 需求评审\n"
            "> 项目总体备注\n"
        )
        doc = markdown_to_doc(md)
        md2 = export_markdown(doc)
        assert _norm_md(md2) == _norm_md(md)


class TestDocToMarkdown:
    def test_export_markdown_title(self):
        doc = {"node": {"text": "标题", "children": []}}
        out = export_markdown(doc)
        assert out.split("\n")[0] == "# 标题"

    def test_indent_two_per_level(self):
        # doc_to_markdown 会渲染传入节点本身，再递归子节点（每层 +2 空格）
        node = {
            "id": "r",
            "text": "root",
            "children": [
                {"id": "c1", "text": "L1", "children": [{"id": "c1a", "text": "L2"}]},
            ],
        }
        out = doc_to_markdown(node, level=0)
        lines = out.split("\n")
        assert lines[0] == "- root"  # 节点自身在 level 0，无缩进
        assert lines[1] == "  - L1"  # level 1 → 2 空格
        assert lines[2] == "    - L2"  # level 2 → 4 空格

    def test_checked_rendering(self):
        node = {
            "id": "r",
            "text": "root",
            "children": [
                {"id": "x", "text": "done", "checked": True},
                {"id": "y", "text": "todo", "checked": False},
                {"id": "z", "text": "plain"},
            ],
        }
        out = doc_to_markdown(node, level=0)
        assert "- [x] done" in out
        assert "- [ ] todo" in out
        assert "- plain" in out

    def test_note_rendering(self):
        node = {
            "id": "r",
            "text": "root",
            "children": [
                {
                    "id": "c",
                    "text": "child",
                    "children": [{"id": "c1", "text": "sub"}],
                    "note": "备注内容",
                }
            ],
        }
        out = doc_to_markdown(node, level=0)
        assert "> 备注内容" in out
        # note 出现在其所属节点（含子树）之后
        assert out.index("> 备注内容") > out.index("- sub")

    def test_export_markdown_invalid_structure_raises(self):
        with pytest.raises(MubuError):
            export_markdown({})  # 无 node，也无 text/children
        with pytest.raises(MubuError):
            export_markdown({"node": {}})  # node 内无 text 也无 children

    def test_export_markdown_accepts_bare_doc(self):
        # doc 本身即 node 结构（无 "node" 包裹）
        out = export_markdown({"text": "裸文档", "children": []})
        assert out == "# 裸文档"


# --------------------------------------------------------------------------- #
# 3. markdown_to_doc 单元
# --------------------------------------------------------------------------- #
class TestMarkdownToDoc:
    def test_multiple_headings_first_is_root(self):
        doc = markdown_to_doc("# 标题A\n# 标题B\n# 标题C")
        assert doc["node"]["text"] == "标题A"
        children_texts = [c["text"] for c in doc["node"]["children"]]
        assert children_texts == ["标题B", "标题C"]

    def test_checked_parsing(self):
        doc = markdown_to_doc("# T\n- [x] done\n- [ ] todo")
        children = doc["node"]["children"]
        assert children[0]["checked"] is True
        assert children[1]["checked"] is False

    def test_note_attached_to_previous_node(self):
        doc = markdown_to_doc("# T\n- item1\n> note for item1")
        assert doc["node"]["children"][0]["note"] == "note for item1"

    def test_nested_depth_via_indent(self):
        md = "- a\n  - b\n    - c\n- d"
        doc = markdown_to_doc(md)
        root_children = doc["node"]["children"]
        assert root_children[0]["text"] == "a"
        assert root_children[0]["children"][0]["text"] == "b"
        assert root_children[0]["children"][0]["children"][0]["text"] == "c"
        assert root_children[1]["text"] == "d"

    def test_ids_increment(self):
        doc = markdown_to_doc("# T\n- a\n- b")
        text_to_id = {c["text"]: c["id"] for c in doc["node"]["children"]}
        assert text_to_id["a"] == "node_1"
        assert text_to_id["b"] == "node_2"


# --------------------------------------------------------------------------- #
# 4. 401 重试仅 1 次（T4 核心）
# --------------------------------------------------------------------------- #
class TestAuthRetry:
    @responses.activate
    def test_401_retries_once_then_success(self, isolated_client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/user/phone_login",
            json={"code": 0, "data": {"token": "new", "id": "u", "name": "n"}},
            status=200,
        )
        # 第一次 API 调用返回 401
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 401, "msg": "登录失效，请重新登录"},
            status=401,
        )
        # 第二次（重试后）成功
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 0, "data": [{"id": "d1", "name": "x"}]},
            status=200,
        )
        with mock.patch.object(
            isolated_client, "login", wraps=isolated_client.login
        ) as mlogin:
            result = isolated_client.get_list("0")
        assert result == [{"id": "d1", "name": "x"}]
        assert mlogin.call_count == 1  # 仅额外重登 1 次

    @responses.activate
    def test_401_continuous_raises_after_one_retry(self, isolated_client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/user/phone_login",
            json={"code": 0, "data": {"token": "new", "id": "u", "name": "n"}},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 401, "msg": "登录失效"},
            status=401,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 401, "msg": "登录失效"},
            status=401,
        )
        with mock.patch.object(
            isolated_client, "login", wraps=isolated_client.login
        ) as mlogin:
            with pytest.raises(MubuError):
                isolated_client.get_list("0")
        # 连续 401：login 只被额外调用 1 次后抛错，不再重登
        assert mlogin.call_count == 1

    @responses.activate
    def test_403_does_not_retry(self, isolated_client):
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 403, "msg": "权限不足"},
            status=403,
        )
        with mock.patch.object(
            isolated_client, "login", wraps=isolated_client.login
        ) as mlogin:
            with pytest.raises(MubuError):
                isolated_client.get_list("0")
        # 403 不触发重登
        assert mlogin.call_count == 0

    @responses.activate
    def test_login_fail_keyword_triggers_retry(self, isolated_client):
        """非 401 但 msg 含登录失效关键字也应触发重登且仅 1 次。"""
        responses.add(
            responses.POST,
            f"{BASE_URL}/user/phone_login",
            json={"code": 0, "data": {"token": "new", "id": "u", "name": "n"}},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 1001, "msg": "token 已过期，请重新登录"},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{BASE_URL}/list/get",
            json={"code": 0, "data": []},
            status=200,
        )
        with mock.patch.object(
            isolated_client, "login", wraps=isolated_client.login
        ) as mlogin:
            result = isolated_client.get_list("0")
        assert result == []
        assert mlogin.call_count == 1


# --------------------------------------------------------------------------- #
# 5. 原子写 token
# --------------------------------------------------------------------------- #
class TestSaveTokenAtomic:
    def test_no_tmp_leftover_and_content_complete(self, tmp_path):
        tok = tmp_path / "tok.json"
        with mock.patch.object(mubu_api, "TOKEN_FILE", tok):
            c = MubuClient(phone="p", password="w")
            c.token = "abc"
            c.user_id = "u1"
            c.username = "name1"
            c._save_token()
            assert tok.exists()
            # 临时文件必须已被 rename 消费，无残留
            assert not (tmp_path / "tok.json.tmp").exists()
            data = json.loads(tok.read_text())
            assert data["token"] == "abc"
            assert data["user_id"] == "u1"
            assert "expires_at" in data

    def test_uses_os_rename(self, tmp_path):
        tok = tmp_path / "tok.json"
        with mock.patch.object(mubu_api, "TOKEN_FILE", tok):
            with mock.patch("os.rename") as mren, \
                    mock.patch("os.chmod") as mchmod:
                c = MubuClient(phone="p", password="w")
                c.token = "x"
                c._save_token()
                assert mren.call_count == 1
                # T5：原子写（rename）之后追加 chmod 0o600
                mchmod.assert_called_once_with(tok, mubu_api.TOKEN_FILE_MODE)


# --------------------------------------------------------------------------- #
# 6. CLI 子命令注册
# --------------------------------------------------------------------------- #
class TestCliParsing:
    def _run(self, argv, monkeypatch):
        """运行 main()，返回 (err, MubuClient_mock, markdown_to_doc_mock)。

        必须在 mock 作用域内捕获 mock 对象，退出 with 后 mubu_api 已恢复为真实类，
        直接在方法内引用 MubuClient 会丢失 return_value。
        """
        monkeypatch.setattr(sys, "argv", ["mubu_api.py"] + argv)
        with mock.patch("mubu_api.MubuClient") as MC, \
                mock.patch("mubu_api.export_markdown", return_value="# x") as EXP, \
                mock.patch("mubu_api.markdown_to_doc", return_value={"node": {}}) as MD, \
                mock.patch("mubu_api.Path") as MP:
            MP.return_value.read_text.return_value = ""
            err = None
            try:
                mubu_api.main()
            except SystemExit as e:  # 仅当发生错误时
                err = e
            return err, MC, MD

    def test_cli_move_parses(self, monkeypatch):
        err, MC, _ = self._run(["move", "item1", "--target", "fid"], monkeypatch)
        assert err is None
        MC.return_value.move.assert_called_once_with("item1", "fid")

    def test_cli_get_export_markdown_parses(self, monkeypatch):
        err, MC, _ = self._run(["get", "doc123", "--export", "markdown"], monkeypatch)
        assert err is None
        MC.return_value.get_doc.assert_called_once_with("doc123")

    def test_cli_create_md_parses(self, monkeypatch):
        err, MC, MD = self._run(
            ["create", "文档名", "--folder", "fid", "--md", "outline.md"], monkeypatch
        )
        assert err is None
        MC.return_value.create_doc.assert_called_once()
        MD.assert_called_once()

    def test_cli_save_md_parses(self, monkeypatch):
        err, MC, MD = self._run(["save", "doc123", "--md", "outline.md"], monkeypatch)
        assert err is None
        MC.return_value.save_doc.assert_called_once()
        MD.assert_called_once()

    def test_cli_create_plain_parses(self, monkeypatch):
        err, MC, _ = self._run(["create", "文档名", "--folder", "fid"], monkeypatch)
        assert err is None
        MC.return_value.create_doc.assert_called_once_with("文档名", "fid", "")


# =========================================================================== #
# M2 (P1) 新增测试：T5 网络健壮性 / .env / 权限，T6 本地搜索
# =========================================================================== #

# --------------------------------------------------------------------------- #
# 7. M2 T5 — MubuError 增强（body 截断 / 非 JSON 友好异常）
# --------------------------------------------------------------------------- #
class TestMubuErrorEnhanced:
    def test_body_truncated_when_string_long(self):
        e = MubuError("x", status_code=500, body="a" * 300)
        assert e.status_code == 500
        assert isinstance(e.body, str)
        assert len(e.body) == 200  # BODY_TRUNCATE

    def test_body_not_truncated_when_dict(self):
        d = {"code": 1, "msg": "x" * 300}
        e = MubuError("x", status_code=500, body=d)
        assert e.body is d  # dict 不截断
        assert e.status_code == 500

    def test_body_not_truncated_when_short_string(self):
        e = MubuError("x", status_code=400, body="short")
        assert e.body == "short"

    @mock.patch("requests.Session.request")
    def test_non_json_response_raises_friendly(self, mreq):
        """_request 对响应体非 JSON 时抛友好 MubuError（含 status/截断 body）。"""
        c = MubuClient(phone="p", password="w")
        c.token = "t"
        resp = mock.Mock()
        resp.status_code = 200
        resp.text = "<html>502 Bad Gateway</html>"
        resp.json.side_effect = ValueError("not json")
        mreq.return_value = resp
        with pytest.raises(MubuError) as ei:
            c._request("POST", "/list/get", auth=False, json={})
        e = ei.value
        assert e.status_code == 200
        assert "502" in e.body


# --------------------------------------------------------------------------- #
# 8. M2 T5 — 网络层重试（超时 / 5xx），最多 2 次重试 = 共 3 次请求
# --------------------------------------------------------------------------- #
class TestNetworkRetry:
    @mock.patch("requests.Session.request")
    def test_timeout_retries_twice_then_success(self, mreq):
        c = MubuClient(phone="p", password="w")
        c.token = "t"
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "data": {}}
        calls = {"n": 0}

        def side(*a, **k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise requests.exceptions.Timeout("timeout")
            return resp

        mreq.side_effect = side
        with mock.patch("time.sleep"):
            out = c._http_request("POST", "http://x/api", {"h": "1"})
        assert out is resp
        assert calls["n"] == 3  # 1 首发 + 2 次重试

    @pytest.mark.parametrize("status", [500, 502])
    @mock.patch("requests.Session.request")
    def test_5xx_retries_then_mubuerror(self, mreq, status):
        c = MubuClient(phone="p", password="w")
        c.token = "t"
        resp = mock.Mock()
        resp.status_code = status
        resp.text = "x" * 500
        mreq.return_value = resp  # 每次都返回 5xx
        with mock.patch("time.sleep"):
            with pytest.raises(MubuError) as ei:
                c._http_request("POST", "http://x/api", {"h": "1"})
        e = ei.value
        assert e.status_code == status
        assert isinstance(e.body, str) and len(e.body) == 200  # 截断
        assert mreq.call_count == 3  # 1 首发 + 2 次重试

    @mock.patch("requests.Session.request")
    def test_5xx_mixed_degrade_then_success(self, mreq):
        c = MubuClient(phone="p", password="w"); c.token = "t"
        seq = [502, 503, 200]
        def side(*a, **k):
            s = seq.pop(0)
            r = mock.Mock(); r.status_code = s; r.text = "x" * 10
            r.json.return_value = {"code": 0, "data": {}} if s == 200 else {"code": 1}
            return r
        mreq.side_effect = side
        with mock.patch("time.sleep"):
            out = c._http_request("POST", "http://x/api", {"h": "1"})
        assert out.status_code == 200
        assert mreq.call_count == 3

    @mock.patch("requests.Session.request")
    def test_connection_error_retries_then_success(self, mreq):
        c = MubuClient(phone="p", password="w"); c.token = "t"
        resp = mock.Mock(); resp.status_code = 200; resp.json.return_value = {"code": 0, "data": {}}
        calls = {"n": 0}
        def side(*a, **k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise requests.exceptions.ConnectionError("conn reset")
            return resp
        mreq.side_effect = side
        with mock.patch("time.sleep"):
            out = c._http_request("POST", "http://x/api", {"h": "1"})
        assert out is resp
        assert calls["n"] == 3


# --------------------------------------------------------------------------- #
# 9. M2 T5 — 401 重试与网络重试互不干扰（关键回归）
# --------------------------------------------------------------------------- #
class TestAuthRetryUnaffectedByNetworkRetry:
    @responses.activate
    def test_401_only_one_relogin_no_network_retry(self, isolated_client):
        responses.add(
            responses.POST, f"{BASE_URL}/user/phone_login",
            json={"code": 0, "data": {"token": "new", "id": "u", "name": "n"}},
            status=200,
        )
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 401, "msg": "登录失效，请重新登录"}, status=401,
        )
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 401, "msg": "登录失效，请重新登录"}, status=401,
        )
        with mock.patch.object(isolated_client, "login", wraps=isolated_client.login) as mlogin:
            with pytest.raises(MubuError):
                isolated_client.get_list("0")
        # 401 分支仅重登 1 次（T4 语义保持）
        assert mlogin.call_count == 1
        # 关键：401 是 4xx，不触发网络层重试 → HTTP 调用恰好 3 次
        # (list 401, login, list 401)；若网络重试被错误触发会显著偏多
        assert len(responses.calls) == 3


# --------------------------------------------------------------------------- #
# 10. M2 T5 — .env 凭据加载（仅环境变量未设置时补全）
# --------------------------------------------------------------------------- #
class TestEnvFileLoading:
    def test_loads_when_env_unset(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mubu_api.os, "environ", {})
        tok = tmp_path / "tok.json"
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tok)
        envf = tmp_path / ".env.mubu"
        envf.write_text("MUBU_PHONE=x\nMUBU_PASSWORD=y\n", encoding="utf-8")
        with mock.patch.object(mubu_api, "ENV_FILE", envf):
            c = MubuClient()
        assert c.phone == "x"
        assert c.password == "y"

    def test_env_var_takes_precedence_over_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mubu_api.os, "environ", {"MUBU_PHONE": "envval"})
        tok = tmp_path / "tok.json"
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tok)
        envf = tmp_path / ".env.mubu"
        envf.write_text("MUBU_PHONE=fileval\nMUBU_PASSWORD=filepw\n", encoding="utf-8")
        with mock.patch.object(mubu_api, "ENV_FILE", envf):
            c = MubuClient()
        assert c.phone == "envval"  # 环境变量优先于文件
        assert c.password == "filepw"  # password 未在 env，从文件补全

    def test_env_file_ignores_comments_blanks_and_strips_quotes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mubu_api.os, "environ", {})
        tok = tmp_path / "tok.json"
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tok)
        envf = tmp_path / ".env.mubu"
        envf.write_text(
            "# 注释行\n\nMUBU_PHONE='x'\nMUBU_PASSWORD=\"y\"\n   \nFOO=bar\n",
            encoding="utf-8",
        )
        with mock.patch.object(mubu_api, "ENV_FILE", envf):
            c = MubuClient()
        assert c.phone == "x"  # 引号被剥离
        assert c.password == "y"
        # 非目标键不被注入环境变量
        assert "FOO" not in mubu_api.os.environ

    def test_env_key_stripped(self, tmp_path, monkeypatch):
        """回归：.env 键名两侧空白需被 key.strip() 去除（M2 第 125 行）。"""
        monkeypatch.delenv("MUBU_PHONE", raising=False)
        env = tmp_path / ".env.mubu"
        env.write_text('  MUBU_PHONE = 13800000000  \n', encoding="utf-8")
        with mock.patch.object(mubu_api, "ENV_FILE", env):
            c = MubuClient(phone="p", password="w")
        c._load_env_file(path=env)
        assert os.getenv("MUBU_PHONE") == "13800000000"


# --------------------------------------------------------------------------- #
# 11. M2 T5 — Token 文件权限 600（_save_token 原子写后 chmod）
# --------------------------------------------------------------------------- #
class TestTokenFilePerms:
    def test_save_token_sets_600(self, tmp_path, monkeypatch):
        tok = tmp_path / ".mubu_token"
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tok)
        c = MubuClient(phone="p", password="w")
        c.token = "abc"
        c.user_id = "u"
        c.username = "n"
        c._save_token()
        mode = oct(os.stat(tok).st_mode & 0o777)
        assert mode == "0o600"


# --------------------------------------------------------------------------- #
# 12. M2 T6 — 本地递归搜索 + format_search
# --------------------------------------------------------------------------- #
class TestSearch:
    @responses.activate
    def test_search_recursive_case_insensitive(self, isolated_client):
        # 树：
        #   root -> [folder Project, doc "Project Plan"]
        #   Project -> [folder "Secret Notes", doc "Project Ideas"]
        #   Secret Notes -> [folder "Project Alpha", doc "Random Notes"]
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 0, "data": {
                "folders": [{"id": "Project", "name": "Project"}],
                "docs": [{"id": "d_plan", "name": "Project Plan"}],
            }}, status=200,
            match=[matchers.json_params_matcher({"folderId": "0"})],
        )
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 0, "data": {
                "folders": [{"id": "Secret Notes", "name": "Secret Notes"}],
                "docs": [{"id": "d_ideas", "name": "Project Ideas"}],
            }}, status=200,
            match=[matchers.json_params_matcher({"folderId": "Project"})],
        )
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 0, "data": {
                "folders": [{"id": "Project Alpha", "name": "Project Alpha"}],
                "docs": [{"id": "d_rand", "name": "Random Notes"}],
            }}, status=200,
            match=[matchers.json_params_matcher({"folderId": "Secret Notes"})],
        )

        search_result = isolated_client.search("project")
        results = search_result["results"]
        # 命中 4 项（≥3）：Project(folder)、Project Plan(doc)、
        # Project Ideas(doc)、Project Alpha(folder)
        assert len(results) >= 3
        names = {(r["name"], r["type"], r["path"]) for r in results}
        assert ("Project", "folder", "") in names
        assert ("Project Plan", "doc", "") in names
        assert ("Project Ideas", "doc", "Project") in names
        assert ("Project Alpha", "folder", "Project/Secret Notes") in names
        # 未达上限，truncated 应为 False
        assert search_result["truncated"] is False

        # 大小写不敏感
        results_upper = isolated_client.search("PROJECT")["results"]
        assert len(results_upper) == len(results)

        # format_search 含 📁 / 📄 分区
        out = mubu_api.format_search(results)
        assert "📁" in out
        assert "📄" in out

    @responses.activate
    def test_search_global_limit_enforced(self, isolated_client):
        # 根文件夹返回 5 个全部命中关键字 "x" 的 doc（x0..x4）。
        # 若全局上限（scripts/mubu_api.py 的 walk() 内 len(results) >= limit 早返回）
        # 未生效，search 会收集到全部 5 项；本测试验证其在 limit=2 时仅收集前 2 项
        # 并早返回（证明上限被强制执行，属"真在测"——移除上限逻辑此处会失败）。
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 0, "data": {
                "folders": [],
                "docs": [{"id": f"d{i}", "name": f"x{i}"} for i in range(5)],
            }}, status=200,
            match=[matchers.json_params_matcher({"folderId": "0"})],
        )

        search_result = isolated_client.search("x", limit=2)
        results = search_result["results"]
        # 上限生效：只收集到 2 项（移除上限逻辑此处会变成 5 项而失败）
        assert len(results) == 2
        # 恰好是前 2 个（x0、x1），随后早返回，x2..x4 不会被收集
        assert {r["name"] for r in results} == {"x0", "x1"}
        # 达到 limit 上限 → truncated 标记为真（结果可能不完整）
        assert search_result["truncated"] is True


# --------------------------------------------------------------------------- #
# 13. M2 T5 — format_list 仅使用 docs（移除 documents 兜底）
# --------------------------------------------------------------------------- #
class TestFormatListDocsOnly:
    def test_documents_key_is_ignored(self):
        data = {
            "folders": [{"id": "f1", "name": "F"}],
            "documents": [{"id": "d1", "name": "D"}],
        }
        out = mubu_api.format_list(data)
        assert "D" not in out            # documents 被忽略
        assert "📄 文档:" not in out      # 无 docs 时不渲染文档区
        assert "F" in out                 # folders 正常渲染

    def test_docs_rendered_normally(self):
        data = {
            "folders": [{"id": "f1", "name": "F"}],
            "docs": [{"id": "d1", "name": "D"}],
        }
        out = mubu_api.format_list(data)
        assert "D" in out
        assert "📄 文档:" in out


# =========================================================================== #
# 14. 排障手 #5 — 真实 API 方法 payload 单测（请求体 JSON + 返回 id 提取）
#     这是质量最大短板：此前 CLI 全程 mock 掉 MubuClient，真实请求体/返回解析
#     完全无覆盖。以下用 responses 断言每个方法的请求体结构与返回 id 提取。
# =========================================================================== #
class TestApiMethodPayloads:
    @responses.activate
    def test_login_request_body_and_token_extraction(self, tmp_path, monkeypatch):
        tok = tmp_path / "tok.json"
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tok)
        responses.add(
            responses.POST, f"{BASE_URL}/user/phone_login",
            json={"code": 0, "data": {"token": "T1", "id": "U1", "name": "alice"}},
            status=200,
            match=[matchers.json_params_matcher(
                {"phone": "13800000000", "password": "pw", "callbackType": 0})],
        )
        c = MubuClient(phone="13800000000", password="pw")
        info = c.login()
        assert c.token == "T1"
        assert info["user_id"] == "U1"
        assert info["username"] == "alice"

    @responses.activate
    def test_create_folder_body_and_id(self, isolated_client):
        responses.add(
            responses.POST, f"{BASE_URL}/list/create_folder",
            json={"code": 0, "data": {"folder": {"id": "F1"}}}, status=200,
            match=[matchers.json_params_matcher(
                {"folderId": "0", "name": "NewFolder"})],
        )
        assert isolated_client.create_folder("NewFolder", "0") == "F1"

    @responses.activate
    def test_create_doc_body_and_id(self, isolated_client):
        responses.add(
            responses.POST, f"{BASE_URL}/list/create_doc",
            json={"code": 0, "data": {"doc": {"id": "D1"}}}, status=200,
            match=[matchers.json_params_matcher(
                {"folderId": "fid", "name": "Doc", "content": "C"})],
        )
        assert isolated_client.create_doc("Doc", "fid", "C") == "D1"

    @responses.activate
    def test_get_doc_body_and_return(self, isolated_client):
        responses.add(
            responses.POST, f"{BASE_URL}/doc/get",
            json={"code": 0, "data": {"node": {"text": "t"}}}, status=200,
            match=[matchers.json_params_matcher({"id": "D9"})],
        )
        assert isolated_client.get_doc("D9") == {"node": {"text": "t"}}

    @responses.activate
    def test_save_doc_body_with_name(self, isolated_client):
        captured = {}

        def cb(request):
            captured["body"] = json.loads(request.body)
            return (200, {}, json.dumps({"code": 0, "data": {}}))

        responses.add_callback(responses.POST, f"{BASE_URL}/doc/save", callback=cb)
        isolated_client.save_doc("D9", "content-here", name="Renamed")
        assert captured["body"] == {"id": "D9", "content": "content-here", "name": "Renamed"}

    @responses.activate
    def test_save_doc_body_without_name(self, isolated_client):
        captured = {}

        def cb(request):
            captured["body"] = json.loads(request.body)
            return (200, {}, json.dumps({"code": 0, "data": {}}))

        responses.add_callback(responses.POST, f"{BASE_URL}/doc/save", callback=cb)
        isolated_client.save_doc("D9", "x")
        assert captured["body"] == {"id": "D9", "content": "x"}
        assert "name" not in captured["body"]

    @responses.activate
    def test_delete_body(self, isolated_client):
        captured = {}

        def cb(request):
            captured["body"] = json.loads(request.body)
            return (200, {}, json.dumps({"code": 0, "data": {}}))

        responses.add_callback(responses.POST, f"{BASE_URL}/list/delete", callback=cb)
        isolated_client.delete("D9")
        assert captured["body"] == {"id": "D9"}

    @responses.activate
    def test_move_body(self, isolated_client):
        captured = {}

        def cb(request):
            captured["body"] = json.loads(request.body)
            return (200, {}, json.dumps({"code": 0, "data": {}}))

        responses.add_callback(responses.POST, f"{BASE_URL}/list/move", callback=cb)
        isolated_client.move("D9", "F2")
        assert captured["body"] == {"id": "D9", "folderId": "F2"}


# --------------------------------------------------------------------------- #
# 15. 排障手 #6 — delete --yes 守卫回归（M5 整改核心）
#     无 --yes：0 次网络调用 + sys.exit(1)；有 --yes：才调用 client.delete。
# --------------------------------------------------------------------------- #
class TestDeleteGuard:
    def _write_token(self, tmp_path):
        tok = tmp_path / "tok.json"
        tok.write_text(json.dumps({
            "token": "t", "user_id": "u", "username": "n",
            "expires_at": time.time() + 3600,
        }))
        return tok

    def _invoke(self, argv, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["mubu_api.py"] + argv)
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", self._write_token(tmp_path))
        err = None
        try:
            mubu_api.main()
        except SystemExit as e:
            err = e
        return err

    @responses.activate
    def test_delete_without_yes_exits_and_no_network(self, monkeypatch, tmp_path, capsys):
        # 即便注册了 /list/delete mock，无 --yes 也应中止、绝不发请求
        responses.add(responses.POST, f"{BASE_URL}/list/delete",
                      json={"code": 0, "data": {}}, status=200)
        err = self._invoke(["delete", "id1"], monkeypatch, tmp_path)
        assert err is not None and err.code == 1
        assert len(responses.calls) == 0
        assert "不可逆" in capsys.readouterr().err

    @responses.activate
    def test_delete_with_yes_calls_api(self, monkeypatch, tmp_path):
        responses.add(responses.POST, f"{BASE_URL}/list/delete",
                      json={"code": 0, "data": {}}, status=200)
        err = self._invoke(["delete", "id1", "--yes"], monkeypatch, tmp_path)
        assert err is None
        assert len(responses.calls) == 1
        assert json.loads(responses.calls[0].request.body) == {"id": "id1"}


# --------------------------------------------------------------------------- #
# 16. P0 #1 — login CLI：移除明文参数，凭据取自环境变量 / 交互式 getpass
# --------------------------------------------------------------------------- #
class TestLoginCliNoPlaintextArgs:
    def _invoke(self, argv, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["mubu_api.py"] + argv)
        monkeypatch.setattr(mubu_api, "TOKEN_FILE", tmp_path / "tok.json")
        err = None
        try:
            mubu_api.main()
        except SystemExit as e:
            err = e
        return err

    @responses.activate
    def test_login_reads_from_env_no_cli_args(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MUBU_PHONE", "13800000000")
        monkeypatch.setenv("MUBU_PASSWORD", "pw")
        responses.add(responses.POST, f"{BASE_URL}/user/phone_login",
                      json={"code": 0, "data": {"token": "T1", "id": "U1", "name": "alice"}},
                      status=200)
        err = self._invoke(["login"], monkeypatch, tmp_path)
        assert err is None
        assert len(responses.calls) == 1
        body = json.loads(responses.calls[0].request.body)
        assert body == {"phone": "13800000000", "password": "pw", "callbackType": 0}

    @responses.activate
    def test_login_prompts_getpass_when_env_missing(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("MUBU_PHONE", raising=False)
        monkeypatch.delenv("MUBU_PASSWORD", raising=False)
        responses.add(responses.POST, f"{BASE_URL}/user/phone_login",
                      json={"code": 0, "data": {"token": "T1", "id": "U1", "name": "alice"}},
                      status=200)
        monkeypatch.setattr("builtins.input", lambda prompt: "13800000000")
        monkeypatch.setattr(mubu_api.getpass, "getpass", lambda prompt: "pw")
        err = self._invoke(["login"], monkeypatch, tmp_path)
        assert err is None
        body = json.loads(responses.calls[0].request.body)
        assert body == {"phone": "13800000000", "password": "pw", "callbackType": 0}


# --------------------------------------------------------------------------- #
# 17. P0 #2 — _safe_local_path：拒绝绝对路径 / .. 越界 / 目录外
# --------------------------------------------------------------------------- #
class TestSafeLocalPath:
    def test_relative_path_under_cwd_allowed(self):
        # 相对路径位于当前工作目录下，应被允许（返回 Path）
        p = mubu_api._safe_local_path("outline.md")
        assert isinstance(p, Path)
        assert p.name == "outline.md"

    def test_absolute_path_rejected(self):
        with pytest.raises(MubuError):
            mubu_api._safe_local_path("/etc/passwd")

    def test_dotdot_traversal_rejected(self):
        with pytest.raises(MubuError):
            mubu_api._safe_local_path("../secret.txt")

    def test_nested_dotdot_traversal_rejected(self):
        with pytest.raises(MubuError):
            mubu_api._safe_local_path("a/../../secret.txt")

    def test_tilde_path_expands_to_absolute_rejected(self):
        # ~ 展开为绝对路径，应被绝对路径规则拒绝（而非静默变成 cwd 下文件）
        with pytest.raises(MubuError):
            mubu_api._safe_local_path("~/.ssh/id_rsa")

    def test_outside_cwd_rejected(self, tmp_path):
        # 越出 cwd 的绝对路径（即便不越级也拒绝）
        other = tmp_path.parent / "outside.md"
        with pytest.raises(MubuError):
            mubu_api._safe_local_path(str(other))


# --------------------------------------------------------------------------- #
# 18. P1 #7 — _is_auth_error 收紧：正常业务错误不误触发重登
# --------------------------------------------------------------------------- #
class TestIsAuthErrorTightened:
    def _resp(self, code):
        r = mock.Mock()
        r.status_code = code
        return r

    def test_normal_business_error_with_token_word_not_auth(self):
        # 含 "token" 的普通业务错误（如"该 token 无权限"）不应触发重登
        result = {"code": 4001, "msg": "该 token 无权限操作此文档"}
        assert mubu_api.MubuClient._is_auth_error(mubu_api.MubuClient, result, self._resp(200)) is False

    def test_explicit_login_expired_triggers(self):
        result = {"code": 1001, "msg": "token 已过期，请重新登录"}
        assert mubu_api.MubuClient._is_auth_error(mubu_api.MubuClient, result, self._resp(200)) is True

    def test_401_always_auth(self):
        result = {"code": 0, "msg": "ok"}
        assert mubu_api.MubuClient._is_auth_error(mubu_api.MubuClient, result, self._resp(401)) is True


# --------------------------------------------------------------------------- #
# 19. P1 #2 — search() 返回结构含 truncated + 环检测
# --------------------------------------------------------------------------- #
class TestSearchTruncationAndCycle:
    @responses.activate
    def test_truncated_flag_true_when_limit_hit(self, isolated_client):
        responses.add(
            responses.POST, f"{BASE_URL}/list/get",
            json={"code": 0, "data": {
                "folders": [],
                "docs": [{"id": f"d{i}", "name": f"x{i}"} for i in range(5)],
            }}, status=200,
            match=[matchers.json_params_matcher({"folderId": "0"})],
        )
        res = isolated_client.search("x", limit=3)
        assert len(res["results"]) == 3
        # 达到 limit 上限 → truncated 标记为真，调用方可知结果不完整
        assert res["truncated"] is True

    @responses.activate
    def test_cycle_detection_no_infinite_recursion(self, isolated_client):
        # 构造环引用：root 含文件夹 A；A 的子文件夹里又含 A 自身。
        # visited 集合去重后 A 只被访问一次，避免无限递归。
        call_count = {"n": 0}

        def cb(request):
            fid = (json.loads(request.body) if request.body else {}).get("folderId", "0")
            call_count["n"] += 1
            if fid == "0":
                return (200, {}, json.dumps({"code": 0, "data": {
                    "folders": [{"id": "A", "name": "A"}], "docs": []}}))
            # A 的子文件夹里再含 A 自身 → 环
            return (200, {}, json.dumps({"code": 0, "data": {
                "folders": [{"id": "A", "name": "A"}],
                "docs": [{"id": "d_loop", "name": "loopy"}]}}))

        responses.add_callback(responses.POST, f"{BASE_URL}/list/get", callback=cb)
        res = isolated_client.search("loop", max_depth=10, max_requests=200)
        # 因 visited 去重，A 只被访问一次（root + A），不会无限递归
        # （否则会远超 max_requests 或陷入死循环）
        assert call_count["n"] <= 5
        assert res["truncated"] is False
        # 环内的 doc "loopy" 命中关键字 "loop" 仍应被收集
        assert any(r["name"] == "loopy" for r in res["results"])


# --------------------------------------------------------------------------- #
# 20. P1 #1 — 错误操作指引：按 HTTP 状态码给出下一步文案
# --------------------------------------------------------------------------- #
class TestErrorGuidanceMessages:
    @responses.activate
    def test_401_message_guides_credential_check(self, isolated_client):
        responses.add(responses.POST, f"{BASE_URL}/user/phone_login",
                      json={"code": 0, "data": {"token": "new", "id": "u", "name": "n"}}, status=200)
        responses.add(responses.POST, f"{BASE_URL}/list/get",
                      json={"code": 401, "msg": "登录失效"}, status=401)
        responses.add(responses.POST, f"{BASE_URL}/list/get",
                      json={"code": 401, "msg": "登录失效"}, status=401)
        with mock.patch.object(isolated_client, "login", wraps=isolated_client.login) as mlogin:
            with pytest.raises(MubuError) as ei:
                isolated_client.get_list("0")
        # 401：指引用户检查凭据（重试 1 次后抛错）
        assert "登录失效或密码错误，请检查凭据后重试" in str(ei.value)
        assert mlogin.call_count == 1

    @responses.activate
    def test_403_message_guides_permission(self, isolated_client):
        responses.add(responses.POST, f"{BASE_URL}/list/get",
                      json={"code": 403, "msg": "权限不足"}, status=403)
        with pytest.raises(MubuError) as ei:
            isolated_client.get_list("0")
        # 403：指引用户确认账号权限
        assert "权限不足，请确认账号权限" in str(ei.value)

    @mock.patch("requests.Session.request")
    def test_5xx_message_guides_retry_later(self, mreq):
        c = MubuClient(phone="p", password="w"); c.token = "t"
        resp = mock.Mock(); resp.status_code = 503; resp.text = "x" * 500
        mreq.return_value = resp
        with mock.patch("time.sleep"):
            with pytest.raises(MubuError) as ei:
                c._http_request("POST", "http://x/api", {"h": "1"})
        # 5xx：指引用户稍后重试
        assert "幕布服务暂不可用，请稍后重试" in str(ei.value)

    @mock.patch("requests.Session.request")
    def test_network_error_message_guides_network_check(self, mreq):
        c = MubuClient(phone="p", password="w"); c.token = "t"
        mreq.side_effect = requests.exceptions.ConnectionError("conn reset")
        with mock.patch("time.sleep"):
            with pytest.raises(MubuError) as ei:
                c._http_request("POST", "http://x/api", {"h": "1"})
        # 网络异常：指引用户检查网络
        assert "网络连接失败，请检查网络" in str(ei.value)


# --------------------------------------------------------------------------- #
# 21. P1 #3 — 移除冗余 ensure_login()：高层方法仅走 auth=True
# --------------------------------------------------------------------------- #
class TestEnsureLoginRedundantRemoved:
    @responses.activate
    def test_create_folder_does_not_call_ensure_login(self, isolated_client):
        responses.add(responses.POST, f"{BASE_URL}/list/create_folder",
                      json={"code": 0, "data": {"folder": {"id": "F1"}}}, status=200,
                      match=[matchers.json_params_matcher(
                          {"folderId": "0", "name": "NewFolder"})])
        with mock.patch.object(isolated_client, "ensure_login",
                              wraps=isolated_client.ensure_login) as mel:
            assert isolated_client.create_folder("NewFolder", "0") == "F1"
        # 冗余的 ensure_login() 已移除：仅由 _request(auth=True) 内部处理
        assert mel.call_count == 0

    @responses.activate
    def test_get_list_still_works_without_ensure_login(self, isolated_client):
        responses.add(responses.POST, f"{BASE_URL}/list/get",
                      json={"code": 0, "data": {"folders": [], "docs": []}}, status=200)
        with mock.patch.object(isolated_client, "ensure_login",
                              wraps=isolated_client.ensure_login) as mel:
            isolated_client.get_list("0")
        assert mel.call_count == 0


# --------------------------------------------------------------------------- #
# 22. P1 #16 — 日志规范：分级 + 敏感信息脱敏
# --------------------------------------------------------------------------- #
class TestLoggingSanitization:
    def test_sensitive_data_not_logged(self, monkeypatch):
        # 明文密码仅出现在 login 请求体，绝不进入日志
        buf = __import__("io").StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        mubu_api.logger.addHandler(handler)
        mubu_api.logger.setLevel(logging.DEBUG)
        try:
            monkeypatch.setenv("MUBU_PASSWORD", "SUPER_SECRET_PW")
            with mock.patch("requests.Session.request") as mreq:
                resp = mock.Mock(); resp.status_code = 200
                resp.json.return_value = {"code": 1, "msg": "密码错误"}
                mreq.return_value = resp
                c = MubuClient()
                with pytest.raises(MubuError):
                    c.login()
            log_text = buf.getvalue()
            # 日志中不应出现明文密码（仅记录 msg，不记录请求体/响应体）
            assert "SUPER_SECRET_PW" not in log_text
        finally:
            mubu_api.logger.removeHandler(handler)

    def test_verbose_enables_debug(self, capsys):
        mubu_api._configure_logging(verbose=True)
        assert mubu_api.logger.level == logging.DEBUG
        mubu_api.logger.debug("DBG_MARKER")
        assert "DBG_MARKER" in capsys.readouterr().err
        mubu_api._configure_logging(verbose=False)
        assert mubu_api.logger.level == logging.WARNING


# --------------------------------------------------------------------------- #
# 23. P1 #1 — examples/weekly.md 示例大纲可被正确解析
# --------------------------------------------------------------------------- #
class TestExamples:
    def test_weekly_md_exists_and_parses(self):
        example = REPO_ROOT / "examples" / "weekly.md"
        assert example.exists(), "examples/weekly.md 缺失"
        doc = markdown_to_doc(example.read_text(encoding="utf-8"))
        # 顶层标题作为 root，且至少含一个子节点
        assert doc["node"]["text"]
        assert len(doc["node"].get("children", [])) >= 1


# --------------------------------------------------------------------------- #
# 24. P2 #22 — 复用 requests.Session 连接池
# --------------------------------------------------------------------------- #
class TestSessionReuse:
    def test_client_holds_requests_session(self):
        c = MubuClient(phone="p", password="w")
        assert isinstance(c._session, requests.Session)

    @mock.patch("requests.Session.request")
    def test_session_request_is_reused(self, mreq):
        c = MubuClient(phone="p", password="w")
        c.token = "t"
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = {"code": 0, "data": {}}
        mreq.return_value = resp
        c._http_request("POST", "http://x/api", {"h": "1"})
        c._http_request("POST", "http://x/api", {"h": "1"})
        # 两次调用都走同一个 session.request（连接池复用）
        assert mreq.call_count == 2


# --------------------------------------------------------------------------- #
# 25. P2 #21 — 依赖拆分（运行时 / 开发分离）
# --------------------------------------------------------------------------- #
class TestRequirementsSplit:
    def test_requirements_dev_exists(self):
        dev = REPO_ROOT / "requirements-dev.txt"
        assert dev.exists(), "requirements-dev.txt 应存在（开发依赖独立拆分）"
        text = dev.read_text(encoding="utf-8")
        assert "pytest" in text
        assert "responses" in text
        # responses 应带上限，避免意外大版本跃迁
        assert "<1" in text

    def test_runtime_requirements_has_only_requests(self):
        rt = REPO_ROOT / "requirements.txt"
        text = rt.read_text(encoding="utf-8")
        assert "requests" in text
        assert "pytest" not in text
        assert "responses" not in text


# --------------------------------------------------------------------------- #

