"""Tests for :mod:`py_manage_nginx.manager`."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from py_manage_nginx.manager import (
    CommandResult,
    request_letsencrypt_certificate,
)


class _CommandRecorder:
    """Collect arguments received by the patched command runner."""

    def __init__(self) -> None:
        self.last_command: list[str] | None = None
        self.last_use_sudo: bool | None = None
        self.last_timeout: float | None = None

    def __call__(
        self,
        command: list[str],
        *,
        use_sudo: bool,
        timeout: float | None,
    ) -> CommandResult:
        self.last_command = command
        self.last_use_sudo = use_sudo
        self.last_timeout = timeout
        return CommandResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
            error=None,
        )


def test_request_certificate_with_webroot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The certbot command should include all configured options."""

    recorder = _CommandRecorder()
    monkeypatch.setattr(
        "py_manage_nginx.manager._run_command",
        recorder,
    )

    result = request_letsencrypt_certificate(
        " example.com ",
        email=" admin@example.com ",
        additional_domains=["www.example.com", "example.com"],
        webroot_path=Path("/var/www/html"),
        use_sudo=True,
        staging=True,
        dry_run=True,
        preferred_challenges=["http-01", ""],
        extra_args=["--force-renewal"],
        timeout=120,
    )

    assert recorder.last_use_sudo is True
    assert recorder.last_timeout == 120
    assert result.ok

    assert recorder.last_command == [
        "certbot",
        "certonly",
        "--non-interactive",
        "--keep-until-expiring",
        "--agree-tos",
        "--email",
        "admin@example.com",
        "--staging",
        "--dry-run",
        "--webroot",
        "-w",
        "/var/www/html",
        "--preferred-challenges",
        "http-01",
        "-d",
        "example.com",
        "-d",
        "www.example.com",
        "--force-renewal",
    ]


def test_request_certificate_without_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should fall back to the nginx authenticator."""

    recorder = _CommandRecorder()
    monkeypatch.setattr("py_manage_nginx.manager._run_command", recorder)

    request_letsencrypt_certificate(
        "test.example.org",
        preferred_challenges=[],
    )

    assert recorder.last_use_sudo is False
    assert recorder.last_timeout is None
    assert recorder.last_command == [
        "certbot",
        "certonly",
        "--non-interactive",
        "--keep-until-expiring",
        "--agree-tos",
        "--register-unsafely-without-email",
        "--nginx",
        "-d",
        "test.example.org",
    ]


def test_request_certificate_requires_domain() -> None:
    """Providing an empty domain should raise a ``ValueError``."""

    with pytest.raises(ValueError):
        request_letsencrypt_certificate("   ")
