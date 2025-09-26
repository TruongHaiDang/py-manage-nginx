"""Integration tests and utilities for py-manage-nginx."""

from py_manage_nginx.manager import list_sites, reload_nginx, restart_nginx, test_nginx_configuration
from py_manage_nginx.hosting import create_hosting, remove_hosting
from pathlib import Path
import shutil
import pytest
import os


# Absolute paths for demo static site assets used in the upload helper.
STATIC_SITE_DIR = Path(__file__).parent / "static_site"
SOURCE_CODE_HOSTING_DIR = Path(__file__).parent / "source_code_hosting"


def upload_static_site_to_sources(
    *,
    static_site_dir: Path | None = None,
    destination_dir: Path | None = None,
) -> Path:
    """Upload the demo static site to the local hosting sources directory.

    Parameters
    ----------
    static_site_dir:
        Optional override pointing to the static website that should be copied.
        When omitted the helper uses the bundled assets under ``tests/static_site``.
    destination_dir:
        Optional override for the upload target. Defaults to ``tests/source_code_hosting``.

    Returns
    -------
    Path
        The path pointing to the directory that now contains the static website.

    Raises
    ------
    FileNotFoundError
        Raised when the ``static_site_dir`` does not exist on disk.
    """

    resolved_source = static_site_dir or STATIC_SITE_DIR
    resolved_destination = destination_dir or SOURCE_CODE_HOSTING_DIR

    if not resolved_source.exists():
        raise FileNotFoundError(f"Static site directory not found: {resolved_source}")

    # Recreate the destination to ensure a clean copy and avoid stale artifacts.
    if resolved_destination.exists():
        shutil.rmtree(resolved_destination)
    resolved_destination.mkdir(parents=True, exist_ok=True)

    # copytree with dirs_exist_ok keeps the directory structure intact efficiently.
    shutil.copytree(resolved_source, resolved_destination, dirs_exist_ok=True)

    return resolved_destination


SITE_NAME = "test-site-ssl"
SERVER_NAMES = ["test.example.com", "www.test.example.com"]


def test_create_hosting_no_cert():
    """Test tạo hosting và kiểm tra sự tồn tại trên nginx thật."""
    if os.geteuid() != 0:
        pytest.skip("Cần chạy bằng root (sudo) để test thật.")

    nginx_root = Path("/etc/nginx")
    web_root_base = Path("/var/www")
    log_directory = Path("/var/log/nginx")

    # Tạo hosting mới
    result = create_hosting(
        site_name=SITE_NAME,
        server_names=SERVER_NAMES,
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
        isCert=True,
        use_sudo=True,
        nginx_binary="nginx",
        controller="systemctl",
    )

    assert result.ok, f"Reload nginx thất bại: {result.stderr or result.stdout}"

    # Kiểm tra sự tồn tại
    expected_config = nginx_root / "sites-available" / f"{SITE_NAME}.conf"
    expected_link = nginx_root / "sites-enabled" / f"{SITE_NAME}.conf"
    document_root = web_root_base / SITE_NAME

    assert expected_config.exists(), f"Thiếu file cấu hình {expected_config}"
    assert expected_link.exists() and expected_link.is_symlink(), f"Symlink không hợp lệ {expected_link}"
    assert document_root.is_dir(), f"Document root không tồn tại {document_root}"

    sites = list_sites(root=nginx_root, directory="sites-enabled")
    assert f"{SITE_NAME}.conf" in [s.name for s in sites]

def test_create_hosting_with_cert():
    """Test tạo hosting với chứng chỉ tự ký (self-signed) dùng API của hosting.py."""
    if os.geteuid() != 0:
        pytest.skip("Cần chạy bằng root (sudo) để test thật.")

    nginx_root = Path("/etc/nginx")
    web_root_base = Path("/var/www")
    log_directory = Path("/var/log/nginx")

    # Chứng chỉ tự ký theo hướng dẫn trong README
    cert_dir = Path("/etc/nginx/ssl/test.local")
    fullchain_path = cert_dir / "fullchain.pem"
    privkey_path = cert_dir / "privkey.pem"

    if not (fullchain_path.exists() and privkey_path.exists()):
        pytest.skip(
            "Thiếu chứng chỉ tự ký. Hãy tạo theo README: openssl -> /etc/nginx/ssl/test.local"
        )

    # Sử dụng domain khớp với chứng chỉ
    site_name_ssl: str = SITE_NAME
    server_names_ssl: list[str] = ["test.local"]

    # Tạo hosting mới chỉ định trực tiếp đường dẫn chứng chỉ tự ký qua tham số API
    result = create_hosting(
        site_name=site_name_ssl,
        server_names=server_names_ssl,
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
        isCert=True,
        ssl_certificate_path=fullchain_path,
        ssl_certificate_key_path=privkey_path,
        use_sudo=True,
        nginx_binary="nginx",
        controller="systemctl",
    )

    assert result.ok, f"Reload nginx thất bại: {result.stderr or result.stdout}"

    # Kiểm tra sự tồn tại
    expected_config = nginx_root / "sites-available" / f"{site_name_ssl}.conf"
    expected_link = nginx_root / "sites-enabled" / f"{site_name_ssl}.conf"
    document_root = web_root_base / site_name_ssl

    assert expected_config.exists(), f"Thiếu file cấu hình {expected_config}"
    assert expected_link.exists() and expected_link.is_symlink(), f"Symlink không hợp lệ {expected_link}"
    assert document_root.is_dir(), f"Document root không tồn tại {document_root}"

    sites = list_sites(root=nginx_root, directory="sites-enabled")
    assert f"{site_name_ssl}.conf" in [s.name for s in sites]

def test_remove_hosting():
    """Test remove_hosting xóa site đã tạo và idempotent khi xóa lại."""
    if os.geteuid() != 0:
        pytest.skip("Cần chạy bằng root (sudo) để test thật.")

    nginx_root = Path("/etc/nginx")
    web_root_base = Path("/var/www")
    log_directory = Path("/var/log/nginx")

    # Xóa site (dù tồn tại hay không)
    result = remove_hosting(
        site_name=SITE_NAME,
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
        use_sudo=True,
        nginx_binary="nginx",
        controller="systemctl",
    )
    assert result.ok, f"Reload nginx thất bại khi remove {SITE_NAME}: {result.stderr or result.stdout}"

    # Đảm bảo site không còn
    expected_config = nginx_root / "sites-available" / f"{SITE_NAME}.conf"
    expected_link = nginx_root / "sites-enabled" / f"{SITE_NAME}.conf"
    document_root = web_root_base / SITE_NAME
    assert not expected_config.exists()
    assert not expected_link.exists()
    assert not document_root.exists()

    sites = list_sites(root=nginx_root, directory="sites-enabled")
    assert f"{SITE_NAME}.conf" not in [s.name for s in sites]

    # Gọi lại lần nữa để kiểm tra idempotent
    again = remove_hosting(
        site_name=SITE_NAME,
        nginx_root=nginx_root,
        web_root_base=web_root_base,
        log_directory=log_directory,
        use_sudo=True,
        nginx_binary="nginx",
        controller="systemctl",
    )
    assert again.ok

def test_list_sites():
    sites = list_sites()
    assert isinstance(sites, list)
    assert all(isinstance(s, Path) for s in sites)

def test_reload_nginx():
    result = reload_nginx(use_sudo=True)
    assert result.ok, f"reload nginx failed: {result.stderr or result.stdout}"

def test_restart_nginx():
    result = restart_nginx(use_sudo=True)
    assert result.ok, f"restart nginx failed: {result.stderr or result.stdout}"

def test_test_nginx_configuration():
    result = test_nginx_configuration(use_sudo=True)
    assert result.ok, f"restart nginx failed: {result.stderr or result.stdout}"


if __name__ == "__main__":
    # Cho phép người phát triển nhanh chóng đồng bộ website tĩnh vào thư mục nguồn.
    upload_static_site_to_sources()
