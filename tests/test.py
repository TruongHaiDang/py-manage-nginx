from py_manage_nginx.manager import list_sites, reload_nginx, restart_nginx, test_nginx_configuration
from py_manage_nginx.hosting import create_hosting, remove_hosting
from pathlib import Path
import pytest
import os


SITE_NAME = "test-site"
SERVER_NAMES = ["test.example.com", "www.test.example.com"]


def test_create_hosting():
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
        isCert=False,
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
