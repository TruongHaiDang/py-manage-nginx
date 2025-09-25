"""High level helpers for provisioning and removing Nginx sites."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from . import manager

# Default configuration template for newly provisioned sites. Using a template
# keeps the logic simple to read and lets callers provide their own layout when
# needed without touching the core implementation. The default enables HTTPS
# and redirects HTTP traffic to the secure endpoint.
DEFAULT_CONFIG_TEMPLATE = """server {{
    listen 80;
    listen [::]:80;

    server_name {server_name};

    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name {server_name};

    root {root};
    index index.html index.htm;

    access_log {access_log};
    error_log {error_log};

    ssl_certificate {ssl_certificate};
    ssl_certificate_key {ssl_certificate_key};

    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""

# Alternate template that skips TLS configuration. Used when a caller does not
# have certificates yet but still wants to provision a basic HTTP site.
DEFAULT_CONFIG_TEMPLATE_NO_SSL = """server {{
    listen 80;
    listen [::]:80;

    server_name {server_name};

    root {root};
    index index.html index.htm;

    access_log {access_log};
    error_log {error_log};

    location / {{
        try_files $uri $uri/ =404;
    }}
}}
"""


__all__ = ["create_hosting", "remove_hosting"]


def create_hosting(
    site_name: str,
    server_names: Sequence[str] | str,
    *,
    nginx_root: Path = manager.DEFAULT_ROOT,
    web_root_base: Path = Path("/var/www"),
    log_directory: Path = Path("/var/log/nginx"),
    config_filename: str | None = None,
    template: str | None = None,
    isCert: bool = True,
    use_sudo: bool = False,
    nginx_binary: str = "nginx",
    controller: str = "systemctl",
) -> manager.CommandResult:
    """Provision a new Nginx site and reload the service.

    Parameters
    ----------
    site_name:
        Logical identifier for the site. The name is reused to build the
        configuration file and the document root directory.
    server_names:
        Domain names that should respond to the new site. Accepts either a
        single string or a sequence of names.
    nginx_root:
        Root directory of the target Nginx installation. Defaults to the
        project-wide constant, matching standard Linux layouts.
    web_root_base:
        Parent directory for site source code. The actual document root is
        created as ``web_root_base / site_name`` if it is missing.
    log_directory:
        Location where log files should be stored. The template references the
        computed paths but the directory is not created automatically to avoid
        requiring elevated privileges when unnecessary.
    config_filename:
        Optional custom filename for the configuration stored in
        ``sites-available`` and linked from ``sites-enabled``. When omitted the
        value defaults to ``"{site_name}.conf"``.
    template:
        Custom configuration template. The string must contain ``{server_name}``,
        ``{root}``, ``{access_log}``, ``{error_log}``, ``{ssl_certificate}`` and
        ``{ssl_certificate_key}`` placeholders when ``isCert`` is ``True``. When
        ``isCert`` is ``False`` the default template does not reference SSL
        placeholders, but custom templates may still do so if desired.
    isCert:
        Toggle TLS directives in the default template. When set to ``False`` the
        generated configuration only serves plain HTTP traffic.
    use_sudo:
        Forwarded to the helper functions in :mod:`manager` when executing
        system commands.
    nginx_binary:
        Binary used to run ``nginx -t``.
    controller:
        Service controller used for reloading the service, defaults to
        ``systemctl``.

    Returns
    -------
    manager.CommandResult
        Result of the ``systemctl reload nginx`` invocation.

    Raises
    ------
    ValueError
        If the provided ``site_name`` or ``server_names`` are invalid.
    FileExistsError
        If a configuration file already exists for ``site_name``.
    RuntimeError
        If the generated configuration fails ``nginx -t`` or the reload command
        does not succeed.
    """

    _validate_site_name(site_name)

    normalized_server_names = _normalize_server_names(server_names)
    if not normalized_server_names:
        raise ValueError("server_names must contain at least one non-empty name")

    config_basename = config_filename or f"{site_name}.conf"

    # Compute the key filesystem locations used during provisioning.
    sites_available_path = nginx_root / "sites-available" / config_basename
    sites_enabled_path = nginx_root / "sites-enabled" / config_basename
    document_root = web_root_base / site_name
    access_log_path = log_directory / f"{site_name}.access.log"
    error_log_path = log_directory / f"{site_name}.error.log"

    if sites_available_path.exists():
        raise FileExistsError(f"configuration already exists: {sites_available_path}")

    sites_available_path.parent.mkdir(parents=True, exist_ok=True)
    sites_enabled_path.parent.mkdir(parents=True, exist_ok=True)
    document_root.mkdir(parents=True, exist_ok=True)

    certificate_path: Path | None
    certificate_key_path: Path | None

    if isCert:
        certificate_path, certificate_key_path = _default_certificate_paths(
            normalized_server_names
        )
    else:
        certificate_path = None
        certificate_key_path = None

    applied_template = template or (
        DEFAULT_CONFIG_TEMPLATE if isCert else DEFAULT_CONFIG_TEMPLATE_NO_SSL
    )

    rendered_config = _render_config(
        applied_template,
        server_names=normalized_server_names,
        document_root=document_root,
        access_log=access_log_path,
        error_log=error_log_path,
        ssl_certificate=certificate_path,
        ssl_certificate_key=certificate_key_path,
    )
    sites_available_path.write_text(rendered_config, encoding="utf-8")

    # Ensure we do not leave stale symlinks that could refer to a removed file.
    if sites_enabled_path.exists() or sites_enabled_path.is_symlink():
        sites_enabled_path.unlink()

    try:
        sites_enabled_path.symlink_to(sites_available_path)
    except OSError as exc:  # noqa: PERF203 - single attempt keeps code simple
        sites_available_path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to enable site: {exc}") from exc

    test_result = manager.test_nginx_configuration(
        nginx_binary=nginx_binary,
        use_sudo=use_sudo,
    )

    if not test_result.ok:
        # Roll back activation when the configuration fails validation.
        sites_enabled_path.unlink(missing_ok=True)
        raise RuntimeError(
            "nginx configuration test failed: "
            f"{test_result.stderr or test_result.stdout or test_result.error}"
        )

    reload_result = manager.reload_nginx(use_sudo=use_sudo, controller=controller)
    if not reload_result.ok:
        raise RuntimeError(
            "failed to reload nginx: "
            f"{reload_result.stderr or reload_result.stdout or reload_result.error}"
        )

    return reload_result


def remove_hosting(
    site_name: str,
    *,
    nginx_root: Path = manager.DEFAULT_ROOT,
    web_root_base: Path = Path("/var/www"),
    log_directory: Path = Path("/var/log/nginx"),
    config_filename: str | None = None,
    use_sudo: bool = False,
    nginx_binary: str = "nginx",
    controller: str = "systemctl",
) -> manager.CommandResult:
    """Remove an existing site configuration and reload Nginx.

    Parameters mirror :func:`create_hosting` for convenience. All filesystem
    artefacts tied to ``site_name`` are removed when present, including the
    document root, configuration file, symbolic link and log files.

    Returns
    -------
    manager.CommandResult
        Result of the ``systemctl reload nginx`` invocation executed after the
        configuration has been cleaned up.

    Raises
    ------
    ValueError
        If ``site_name`` contains path separators.
    RuntimeError
        If the configuration test or reload step fails.
    """

    _validate_site_name(site_name)

    config_basename = config_filename or f"{site_name}.conf"

    sites_available_path = nginx_root / "sites-available" / config_basename
    sites_enabled_path = nginx_root / "sites-enabled" / config_basename
    document_root = web_root_base / site_name
    access_log_path = log_directory / f"{site_name}.access.log"
    error_log_path = log_directory / f"{site_name}.error.log"

    sites_enabled_path.unlink(missing_ok=True)
    sites_available_path.unlink(missing_ok=True)

    # Remove document root and log files as part of the cleanup workflow.
    if document_root.exists():
        shutil.rmtree(document_root)

    access_log_path.unlink(missing_ok=True)
    error_log_path.unlink(missing_ok=True)

    test_result = manager.test_nginx_configuration(
        nginx_binary=nginx_binary,
        use_sudo=use_sudo,
    )

    if not test_result.ok:
        raise RuntimeError(
            "nginx configuration test failed after removal: "
            f"{test_result.stderr or test_result.stdout or test_result.error}"
        )

    reload_result = manager.reload_nginx(use_sudo=use_sudo, controller=controller)
    if not reload_result.ok:
        raise RuntimeError(
            "failed to reload nginx after removal: "
            f"{reload_result.stderr or reload_result.stdout or reload_result.error}"
        )

    return reload_result


def _normalize_server_names(server_names: Sequence[str] | str) -> list[str]:
    """Return a list of unique, non-empty server names."""

    if isinstance(server_names, str):
        candidates = [server_names]
    else:
        candidates = list(server_names)

    filtered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        filtered.append(normalized)
        seen.add(normalized)
    return filtered


def _render_config(
    template: str,
    *,
    server_names: Sequence[str],
    document_root: Path,
    access_log: Path,
    error_log: Path,
    ssl_certificate: Path | None,
    ssl_certificate_key: Path | None,
) -> str:
    """Fill the configuration template with the provided values."""

    rendered = template.format(
        server_name=" ".join(server_names),
        root=str(document_root),
        access_log=str(access_log),
        error_log=str(error_log),
        ssl_certificate="" if ssl_certificate is None else str(ssl_certificate),
        ssl_certificate_key="" if ssl_certificate_key is None else str(ssl_certificate_key),
    )
    # Ensure the file ends with a newline to comply with Unix conventions.
    return rendered.rstrip() + "\n"


def _default_certificate_paths(server_names: Sequence[str]) -> tuple[Path, Path]:
    """Return default certificate locations for the provided server names."""

    primary = _select_certificate_name(server_names)
    certificate_directory = Path("/etc/letsencrypt/live") / primary
    return (
        certificate_directory / "fullchain.pem",
        certificate_directory / "privkey.pem",
    )


def _select_certificate_name(server_names: Sequence[str]) -> str:
    """Pick a filesystem-safe name for certificate lookup."""

    for candidate in server_names:
        normalized = candidate.lstrip("*.")
        if normalized:
            return normalized.replace("*", "").replace("/", "")

    # Fallback to the first entry stripped of path separators and wildcards.
    fallback = server_names[0] if server_names else "default"
    sanitized = fallback.replace("*", "").replace("/", "")
    return sanitized or "default"


def _validate_site_name(site_name: str) -> None:
    """Ensure *site_name* does not contain path separators."""

    stripped = site_name.strip()
    if not stripped:
        raise ValueError("site_name must be a non-empty string")

    if Path(stripped).name != stripped:
        raise ValueError("site_name must not contain path separators")
