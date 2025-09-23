"""Tests for :mod:`py_manage_nginx.hosting`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from py_manage_nginx import hosting, manager


# A minimal configuration template that keeps the focus of the tests on the
# surrounding provisioning logic. The project default template uses literal
# braces that interfere with :func:`str.format`, therefore the tests rely on a
# simplified variant that only exercises the dynamic placeholders.
SIMPLE_TEMPLATE = (
    "server_name {server_name};\n"
    "root {root};\n"
    "access_log {access_log};\n"
    "error_log {error_log};\n"
)


def _success_result(command: tuple[str, ...]) -> manager.CommandResult:
    """Return a successful :class:`~py_manage_nginx.manager.CommandResult`."""

    return manager.CommandResult(
        command=command,
        returncode=0,
        stdout="success",
        stderr="",
        error=None,
    )


def _failure_result(command: tuple[str, ...], *, message: str) -> manager.CommandResult:
    """Return a failed :class:`~py_manage_nginx.manager.CommandResult`."""

    return manager.CommandResult(
        command=command,
        returncode=1,
        stdout="",
        stderr=message,
        error=None,
    )


def test_create_hosting_successful_provision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``create_hosting`` writes files, links them and reloads Nginx."""

    nginx_root = tmp_path / "nginx"
    web_root_base = tmp_path / "www"
    log_directory = tmp_path / "logs"

    recorded: dict[str, tuple[str, bool]] = {}

    def fake_test_nginx_configuration(*, nginx_binary: str, use_sudo: bool) -> manager.CommandResult:
        recorded["test"] = (nginx_binary, use_sudo)
        return _success_result((nginx_binary, "-t"))

    reload_result = _success_result(("systemctl", "reload", "nginx"))

    def fake_reload_nginx(*, use_sudo: bool, controller: str) -> manager.CommandResult:
        recorded["reload"] = (controller, use_sudo)
        return reload_result

    monkeypatch.setattr(hosting.manager, "test_nginx_configuration", fake_test_nginx_configuration)
    monkeypatch.setattr(hosting.manager, "reload_nginx", fake_reload_nginx)

    result = hosting.create_hosting(
        "example",
        ("example.org", " example.org ", "example.net", ""),
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
        template=SIMPLE_TEMPLATE,
    )

    sites_available_path = nginx_root / "sites-available" / "example.conf"
    sites_enabled_path = nginx_root / "sites-enabled" / "example.conf"
    document_root = web_root_base / "example"

    assert result is reload_result
    assert recorded["test"] == ("nginx", False)
    assert recorded["reload"] == ("systemctl", False)
    assert sites_available_path.exists()
    assert sites_enabled_path.is_symlink()
    assert os.readlink(sites_enabled_path) == str(sites_available_path)
    assert document_root.is_dir()

    rendered = sites_available_path.read_text(encoding="utf-8")
    assert "server_name example.org example.net;" in rendered
    assert f"root {document_root}" in rendered
    assert f"access_log {log_directory / 'example.access.log'}" in rendered
    assert f"error_log {log_directory / 'example.error.log'}" in rendered


def test_create_hosting_rejects_existing_configuration(tmp_path: Path) -> None:
    """``create_hosting`` refuses to overwrite an existing configuration."""

    nginx_root = tmp_path / "nginx"
    config_path = nginx_root / "sites-available" / "example.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        hosting.create_hosting(
            "example",
            ["example.org"],
            nginx_root=nginx_root,
            web_root_base=tmp_path / "www",
            log_directory=tmp_path / "logs",
            template=SIMPLE_TEMPLATE,
        )


def test_create_hosting_requires_server_names(tmp_path: Path) -> None:
    """``create_hosting`` validates the ``server_names`` argument."""

    with pytest.raises(ValueError):
        hosting.create_hosting(
            "example",
            [],
            nginx_root=tmp_path / "nginx",
            web_root_base=tmp_path / "www",
            log_directory=tmp_path / "logs",
            template=SIMPLE_TEMPLATE,
        )


def test_create_hosting_configuration_test_failure_rolls_back_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``nginx -t`` fails the enabled symlink is cleaned up."""

    nginx_root = tmp_path / "nginx"
    web_root_base = tmp_path / "www"
    log_directory = tmp_path / "logs"

    def fake_test_nginx_configuration(*, nginx_binary: str, use_sudo: bool) -> manager.CommandResult:
        return _failure_result((nginx_binary, "-t"), message="invalid config")

    def fail_reload(**kwargs: object) -> manager.CommandResult:  # type: ignore[return-value]
        pytest.fail("reload should not be attempted when the test fails")

    monkeypatch.setattr(hosting.manager, "test_nginx_configuration", fake_test_nginx_configuration)
    monkeypatch.setattr(hosting.manager, "reload_nginx", fail_reload)

    with pytest.raises(RuntimeError):
        hosting.create_hosting(
            "example",
            ["example.org"],
            nginx_root=nginx_root,
            web_root_base=web_root_base,
            log_directory=log_directory,
            template=SIMPLE_TEMPLATE,
        )

    sites_available_path = nginx_root / "sites-available" / "example.conf"
    sites_enabled_path = nginx_root / "sites-enabled" / "example.conf"

    assert sites_available_path.exists()
    assert not sites_enabled_path.exists()


def test_create_hosting_reload_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reload failure is surfaced as a :class:`RuntimeError`."""

    nginx_root = tmp_path / "nginx"
    web_root_base = tmp_path / "www"
    log_directory = tmp_path / "logs"

    monkeypatch.setattr(
        hosting.manager,
        "test_nginx_configuration",
        lambda *, nginx_binary, use_sudo: _success_result((nginx_binary, "-t")),
    )

    def fake_reload(*, use_sudo: bool, controller: str) -> manager.CommandResult:
        return _failure_result((controller, "reload", "nginx"), message="reload failed")

    monkeypatch.setattr(hosting.manager, "reload_nginx", fake_reload)

    with pytest.raises(RuntimeError):
        hosting.create_hosting(
            "example",
            ["example.org"],
            nginx_root=nginx_root,
            web_root_base=web_root_base,
            log_directory=log_directory,
            template=SIMPLE_TEMPLATE,
        )

    sites_enabled_path = nginx_root / "sites-enabled" / "example.conf"
    assert sites_enabled_path.exists()


def test_remove_hosting_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``remove_hosting`` deletes files and triggers a reload."""

    nginx_root = tmp_path / "nginx"
    web_root_base = tmp_path / "www"
    log_directory = tmp_path / "logs"

    sites_available_path = nginx_root / "sites-available" / "example.conf"
    sites_enabled_path = nginx_root / "sites-enabled" / "example.conf"
    document_root = web_root_base / "example"
    access_log = log_directory / "example.access.log"
    error_log = log_directory / "example.error.log"

    sites_available_path.parent.mkdir(parents=True, exist_ok=True)
    sites_enabled_path.parent.mkdir(parents=True, exist_ok=True)
    document_root.mkdir(parents=True, exist_ok=True)
    log_directory.mkdir(parents=True, exist_ok=True)

    sites_available_path.write_text("server {}", encoding="utf-8")
    sites_enabled_path.symlink_to(sites_available_path)
    (document_root / "index.html").write_text("<html></html>", encoding="utf-8")
    access_log.write_text("", encoding="utf-8")
    error_log.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        hosting.manager,
        "test_nginx_configuration",
        lambda *, nginx_binary, use_sudo: _success_result((nginx_binary, "-t")),
    )

    reload_result = _success_result(("systemctl", "reload", "nginx"))

    def fake_reload(*, use_sudo: bool, controller: str) -> manager.CommandResult:
        return reload_result

    monkeypatch.setattr(hosting.manager, "reload_nginx", fake_reload)

    result = hosting.remove_hosting(
        "example",
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
    )

    assert result is reload_result
    assert not sites_available_path.exists()
    assert not sites_enabled_path.exists()
    assert not document_root.exists()
    assert not access_log.exists()
    assert not error_log.exists()


def test_remove_hosting_configuration_test_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in ``nginx -t`` aborts the reload phase."""

    nginx_root = tmp_path / "nginx"
    (nginx_root / "sites-available").mkdir(parents=True)

    monkeypatch.setattr(
        hosting.manager,
        "test_nginx_configuration",
        lambda *, nginx_binary, use_sudo: _failure_result((nginx_binary, "-t"), message="invalid"),
    )

    def fail_reload(**kwargs: object) -> manager.CommandResult:  # type: ignore[return-value]
        pytest.fail("reload should not run when the configuration test fails")

    monkeypatch.setattr(hosting.manager, "reload_nginx", fail_reload)

    with pytest.raises(RuntimeError):
        hosting.remove_hosting(
            "example",
            nginx_root=nginx_root,
            web_root_base=tmp_path / "www",
            log_directory=tmp_path / "logs",
        )


def test_remove_hosting_reload_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reload failures in ``remove_hosting`` propagate to the caller."""

    nginx_root = tmp_path / "nginx"

    monkeypatch.setattr(
        hosting.manager,
        "test_nginx_configuration",
        lambda *, nginx_binary, use_sudo: _success_result((nginx_binary, "-t")),
    )

    monkeypatch.setattr(
        hosting.manager,
        "reload_nginx",
        lambda *, use_sudo, controller: _failure_result((controller, "reload", "nginx"), message="reload failed"),
    )

    with pytest.raises(RuntimeError):
        hosting.remove_hosting(
            "example",
            nginx_root=nginx_root,
            web_root_base=tmp_path / "www",
            log_directory=tmp_path / "logs",
        )
