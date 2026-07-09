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

    @mock.patch("requests.request")
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
    @mock.patch("requests.request")
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
    @mock.patch("requests.request")
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

    @mock.patch("requests.request")
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

    @mock.patch("requests.request")
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

        results = isolated_client.search("project")
        # 命中 4 项（≥3）：Project(folder)、Project Plan(doc)、
        # Project Ideas(doc)、Project Alpha(folder)
        assert len(results) >= 3
        names = {(r["name"], r["type"], r["path"]) for r in results}
        assert ("Project", "folder", "") in names
        assert ("Project Plan", "doc", "") in names
        assert ("Project Ideas", "doc", "Project") in names
        assert ("Project Alpha", "folder", "Project/Secret Notes") in names

        # 大小写不敏感
        results_upper = isolated_client.search("PROJECT")
        assert len(results_upper) == len(results)

        # format_search 含 📁 / 📄 分区
        out = mubu_api.format_search(results)
        assert "📁" in out
        assert "📄" in out


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


# --------------------------------------------------------------------------- #
