#!/usr/bin/env python3
"""restore 命令退出码回归测试。

回收站中没有该项时，`restore` 必须以非零状态退出，否则调用方
（脚本/自动化）无法察觉恢复失败。直接导入 `mubu.cli`（不经过
`mubu_api` 兼容 shim，避免 Windows 无 fcntl 时的导入问题）。
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from mubu import cli as mubu_cli  # noqa: E402


def _run_restore(monkeypatch: pytest.MonkeyPatch, item_id: str, found: bool):
    """运行 `restore <id>`，返回 (SystemExit|None, MubuClient mock)。"""
    monkeypatch.setattr(sys, "argv", ["mubu", "restore", item_id])
    with mock.patch.object(mubu_cli, "MubuClient") as client_cls:
        client_cls.return_value.restore_item.return_value = found
        err = None
        try:
            mubu_cli.main()
        except SystemExit as exc:
            err = exc
        return err, client_cls


def test_restore_missing_id_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    err, client_cls = _run_restore(monkeypatch, "no-such-id", False)
    assert err is not None and err.code == 1
    client_cls.return_value.restore_item.assert_called_once_with("no-such-id")
    assert "no-such-id" in capsys.readouterr().out


def test_restore_found_id_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    err, client_cls = _run_restore(monkeypatch, "trashed-1", True)
    assert err is None
    client_cls.return_value.restore_item.assert_called_once_with("trashed-1")
    assert "trashed-1" in capsys.readouterr().out
