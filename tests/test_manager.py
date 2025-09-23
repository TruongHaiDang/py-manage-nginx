"""Tests for :mod:`py_manage_nginx.manager`."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from py_manage_nginx import manager


def test_list_sites_returns_sorted_files(tmp_path: Path) -> None:
    """``list_sites`` returns sorted file and symlink entries."""

    base = tmp_path / "sites-enabled"
    base.mkdir()

    file_a = base / "a.conf"
    file_a.write_text("", encoding="utf-8")

    target = tmp_path / "target.conf"
    target.write_text("", encoding="utf-8")
    symlink = base / "b.conf"
    symlink.symlink_to(target)

    (base / "ignored").mkdir()

    result = manager.list_sites(root=tmp_path, directory="sites-enabled")
    assert result == [file_a, symlink]


def test_list_sites_missing_directory(tmp_path: Path) -> None:
    """``list_sites`` returns an empty list when the directory is missing."""

    result = manager.list_sites(root=tmp_path, directory="sites-enabled")
    assert result == []


def test_check_certificate_status_with_missing_config(tmp_path: Path) -> None:
    """Missing configuration files are reported to the caller."""

    missing = tmp_path / "sites-enabled" / "ghost.conf"

    statuses = manager.check_certificate_status(sites=[missing])
    assert len(statuses) == 1
    status = statuses[0]
    assert status.site == "ghost.conf"
    assert not status.exists
    assert status.error == "configuration path does not exist"


def test_check_certificate_status_without_ssl_directive(tmp_path: Path) -> None:
    """Configurations without ``ssl_certificate`` generate a clear error."""

    config = tmp_path / "sites-enabled" / "plain.conf"
    config.parent.mkdir(parents=True)
    config.write_text("server { listen 80; }", encoding="utf-8")

    statuses = manager.check_certificate_status(sites=[config])
    assert len(statuses) == 1
    status = statuses[0]
    assert status.site == "plain.conf"
    assert status.error == "no ssl_certificate directive found"


def test_check_certificate_status_collects_all_certificates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``check_certificate_status`` delegates decoding to ``_build_certificate_status``."""

    config = tmp_path / "sites-enabled" / "example.conf"
    config.parent.mkdir(parents=True)
    config.write_text(
        """
        ssl_certificate /etc/ssl/example.pem;
        ssl_certificate   /etc/ssl/extra.pem ;
        """.strip(),
        encoding="utf-8",
    )

    returned_statuses = [
        manager.CertificateStatus(
            site="example.conf",
            certificate=Path("/etc/ssl/example.pem"),
            exists=False,
            not_before=None,
            not_after=None,
            days_remaining=None,
            error="missing",
        ),
        manager.CertificateStatus(
            site="example.conf",
            certificate=Path("/etc/ssl/extra.pem"),
            exists=True,
            not_before=datetime.now(timezone.utc),
            not_after=datetime.now(timezone.utc),
            days_remaining=0,
            error=None,
        ),
    ]

    calls: list[tuple[str, Path]] = []

    def fake_build(site_name: str, cert_path: Path) -> manager.CertificateStatus:
        calls.append((site_name, cert_path))
        return returned_statuses[len(calls) - 1]

    monkeypatch.setattr(manager, "_build_certificate_status", fake_build)

    statuses = manager.check_certificate_status(sites=[config])
    assert statuses == returned_statuses
    assert calls == [
        ("example.conf", Path("/etc/ssl/example.pem")),
        ("example.conf", Path("/etc/ssl/extra.pem")),
    ]


def test_check_certificate_status_uses_list_sites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``sites`` is ``None`` the helper queries :func:`list_sites`."""

    config = tmp_path / "sites-enabled" / "auto.conf"
    config.parent.mkdir(parents=True)
    config.write_text("ssl_certificate /etc/ssl/auto.pem;", encoding="utf-8")

    def fake_list_sites(root: Path) -> list[Path]:
        assert root is tmp_path
        return [config]

    status = manager.CertificateStatus(
        site="auto.conf",
        certificate=Path("/etc/ssl/auto.pem"),
        exists=True,
        not_before=None,
        not_after=None,
        days_remaining=None,
        error=None,
    )

    monkeypatch.setattr(manager, "list_sites", fake_list_sites)
    monkeypatch.setattr(manager, "_build_certificate_status", lambda site, cert: status)

    statuses = manager.check_certificate_status(root=tmp_path, sites=None)
    assert statuses == [status]


def test_extract_certificate_paths_parses_lines(tmp_path: Path) -> None:
    """``_extract_certificate_paths`` collects directive values and strips noise."""

    config = tmp_path / "example.conf"
    config.write_text(
        """
        # comment
        ssl_certificate /etc/ssl/example.pem;
        ssl_certificate   /etc/ssl/extra.pem ;  # trailing comment
        ssl_certificate   /etc/ssl/final.pem
        other_setting value;
        """.strip(),
        encoding="utf-8",
    )

    paths = manager._extract_certificate_paths(config)
    assert paths == [
        Path("/etc/ssl/example.pem"),
        Path("/etc/ssl/extra.pem"),
        Path("/etc/ssl/final.pem"),
    ]


def test_build_certificate_status_missing_file(tmp_path: Path) -> None:
    """Non-existent certificate files are flagged as missing."""

    cert_path = tmp_path / "missing.pem"

    status = manager._build_certificate_status("example", cert_path)
    assert not status.exists
    assert status.error == "certificate file does not exist"


def test_build_certificate_status_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful decodes report validity information."""

    cert_path = tmp_path / "example.pem"
    cert_path.write_text("dummy", encoding="utf-8")

    fake_details = {
        "notBefore": "Aug 10 12:00:00 2024 GMT",
        "notAfter": "Aug 12 12:00:00 2024 GMT",
    }

    def fake_decode(path: str) -> dict[str, Any]:
        assert path == str(cert_path)
        return fake_details

    monkeypatch.setattr(manager.ssl._ssl, "_test_decode_cert", fake_decode)

    status = manager._build_certificate_status("example", cert_path)
    assert status.exists
    assert status.error is None
    assert status.not_before == datetime(2024, 8, 10, 12, tzinfo=timezone.utc)
    assert status.not_after == datetime(2024, 8, 12, 12, tzinfo=timezone.utc)
    assert status.days_remaining is not None


def test_build_certificate_status_decode_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Decode errors propagate the error message to the caller."""

    cert_path = tmp_path / "example.pem"
    cert_path.write_text("dummy", encoding="utf-8")

    def fake_decode(path: str) -> dict[str, Any]:  # type: ignore[return-value]
        raise ValueError("bad certificate")

    monkeypatch.setattr(manager.ssl._ssl, "_test_decode_cert", fake_decode)

    status = manager._build_certificate_status("example", cert_path)
    assert status.exists
    assert status.error == "bad certificate"


def test_run_command_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_run_command`` wraps :func:`subprocess.run` output into ``CommandResult``."""

    recorded: dict[str, list[str]] = {}

    class DummyCompleted:
        returncode = 0
        stdout = "output"
        stderr = "warnings"

    def fake_run(command: list[str], **kwargs: Any) -> DummyCompleted:
        recorded["command"] = command
        return DummyCompleted()

    monkeypatch.setattr(manager.subprocess, "run", fake_run)

    result = manager._run_command(["echo", "test"], use_sudo=True)
    assert recorded["command"] == ["sudo", "echo", "test"]
    assert result.ok
    assert result.stdout == "output"
    assert result.stderr == "warnings"


def test_run_command_file_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing commands return a descriptive ``CommandResult``."""

    def fake_run(command: list[str], **kwargs: Any) -> None:
        raise FileNotFoundError("missing")

    monkeypatch.setattr(manager.subprocess, "run", fake_run)

    result = manager._run_command(["nonexistent"], use_sudo=False)
    assert not result.ok
    assert result.error == "command not found: None"


def test_run_command_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts capture the partial output and return a failure."""

    def fake_run(command: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(command, timeout=1, output="out", stderr="err")

    monkeypatch.setattr(manager.subprocess, "run", fake_run)

    result = manager._run_command(["sleep", "1"], timeout=1)
    assert not result.ok
    assert result.error == "command timed out after 1s"
    assert result.stdout == "out"
    assert result.stderr == "err"


def test_restart_reload_and_test_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """High-level service helpers delegate to ``_run_command`` with the right command."""

    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> manager.CommandResult:
        commands.append(command)
        return manager.CommandResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
            error=None,
        )

    monkeypatch.setattr(manager, "_run_command", fake_run)

    manager.restart_nginx()
    manager.reload_nginx()
    manager.test_nginx_configuration()

    assert commands == [
        ["systemctl", "restart", "nginx"],
        ["systemctl", "reload", "nginx"],
        ["nginx", "-t"],
    ]
