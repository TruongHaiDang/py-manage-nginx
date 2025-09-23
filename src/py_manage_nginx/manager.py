"""Utilities for inspecting and controlling an Nginx installation.

This module provides small, composable helpers that wrap common tasks when
working with an Nginx server: discovering enabled sites, inspecting TLS
certificates and interacting with the system service.
"""

from __future__ import annotations

import ssl
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_ROOT = Path("/etc/nginx")


@dataclass(slots=True)
class CommandResult:
    """Normalized result after executing a shell command."""

    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


@dataclass(slots=True)
class CertificateStatus:
    """Represents the TLS certificate attached to a site configuration."""

    site: str
    certificate: Path | None
    exists: bool
    not_before: datetime | None
    not_after: datetime | None
    days_remaining: int | None
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return (
            self.exists
            and self.error is None
            and self.not_after is not None
            and self.not_after >= datetime.now(timezone.utc)
        )


def list_sites(root: Path | str = DEFAULT_ROOT, directory: str = "sites-enabled") -> list[Path]:
    """Return the available Nginx site configuration files in *directory*.

    By default this targets ``sites-enabled`` so the result mirrors what Nginx
    actively loads. Returned paths preserve symlinks to make it easier to trace
    back to the original file.
    """

    root = Path(root)
    base = root / directory
    if not base.is_dir():
        return []

    sites: list[Path] = []
    for entry in sorted(base.iterdir()):
        if entry.is_file() or entry.is_symlink():
            sites.append(entry)
    return sites


def check_certificate_status(
    root: Path = DEFAULT_ROOT,
    sites: Iterable[Path] | None = None,
) -> list[CertificateStatus]:
    """Inspect TLS certificates referenced by the provided site configs.

    Parameters
    ----------
    root:
        Root directory of the Nginx installation. Only used when *sites* is
        ``None``.
    sites:
        Optional iterable of configuration paths. When omitted, the function
        inspects every file returned by :func:`list_sites`.
    """

    configs = list(sites) if sites is not None else list_sites(root)
    results: list[CertificateStatus] = []

    for config_path in configs:
        site_name = config_path.name
        if not config_path.exists():
            results.append(
                CertificateStatus(
                    site=site_name,
                    certificate=None,
                    exists=False,
                    not_before=None,
                    not_after=None,
                    days_remaining=None,
                    error="configuration path does not exist",
                )
            )
            continue

        certificate_paths = _extract_certificate_paths(config_path)
        if not certificate_paths:
            results.append(
                CertificateStatus(
                    site=site_name,
                    certificate=None,
                    exists=False,
                    not_before=None,
                    not_after=None,
                    days_remaining=None,
                    error="no ssl_certificate directive found",
                )
            )
            continue

        for cert_path in certificate_paths:
            results.append(_build_certificate_status(site_name, cert_path))

    return results


def restart_nginx(*, use_sudo: bool = False, controller: str = "systemctl") -> CommandResult:
    """Restart the Nginx service via ``systemctl`` (or *controller*)."""

    return _run_command([controller, "restart", "nginx"], use_sudo=use_sudo)


def reload_nginx(*, use_sudo: bool = False, controller: str = "systemctl") -> CommandResult:
    """Reload Nginx configuration via ``systemctl reload nginx``."""

    return _run_command([controller, "reload", "nginx"], use_sudo=use_sudo)


def test_nginx_configuration(
    nginx_binary: str = "nginx", *, use_sudo: bool = False
) -> CommandResult:
    """Execute ``nginx -t`` and return the outcome."""

    return _run_command([nginx_binary, "-t"], use_sudo=use_sudo)


def _extract_certificate_paths(config_path: Path) -> list[Path]:
    certificate_paths: list[Path] = []

    try:
        for line in config_path.read_text().splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            if stripped.startswith("ssl_certificate "):
                value = stripped[len("ssl_certificate ") :].strip()
                if value.endswith(";"):
                    value = value[:-1].strip()
                certificate_paths.append(Path(value))
    except UnicodeDecodeError:
        pass

    return certificate_paths


def _build_certificate_status(site_name: str, cert_path: Path) -> CertificateStatus:
    if not cert_path.exists():
        return CertificateStatus(
            site=site_name,
            certificate=cert_path,
            exists=False,
            not_before=None,
            not_after=None,
            days_remaining=None,
            error="certificate file does not exist",
        )

    try:
        details = ssl._ssl._test_decode_cert(str(cert_path))  # type: ignore[attr-defined]
        not_before = _parse_openssl_datetime(details.get("notBefore"))
        not_after = _parse_openssl_datetime(details.get("notAfter"))
    except FileNotFoundError:
        return CertificateStatus(
            site=site_name,
            certificate=cert_path,
            exists=False,
            not_before=None,
            not_after=None,
            days_remaining=None,
            error="certificate file does not exist",
        )
    except Exception as exc:  # noqa: BLE001 - propagate message to caller
        return CertificateStatus(
            site=site_name,
            certificate=cert_path,
            exists=True,
            not_before=None,
            not_after=None,
            days_remaining=None,
            error=str(exc),
        )

    if not_after is None:
        days_remaining = None
    else:
        delta = not_after - datetime.now(timezone.utc)
        days_remaining = int(delta.total_seconds() // 86400)

    return CertificateStatus(
        site=site_name,
        certificate=cert_path,
        exists=True,
        not_before=not_before,
        not_after=not_after,
        days_remaining=days_remaining,
        error=None,
    )


def _parse_openssl_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _run_command(
    command: Sequence[str], *, use_sudo: bool = False, timeout: float | None = None
) -> CommandResult:
    computed_command = ["sudo", *command] if use_sudo else list(command)

    try:
        completed = subprocess.run(  # noqa: S603,S607 - command controlled by caller
            computed_command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            command=tuple(computed_command),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            error=None,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=tuple(computed_command),
            returncode=None,
            stdout="",
            stderr="",
            error=f"command not found: {exc.filename}",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        return CommandResult(
            command=tuple(computed_command),
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            error=f"command timed out after {timeout}s",
        )

