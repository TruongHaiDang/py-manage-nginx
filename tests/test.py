"""Integration tests and utilities for py-manage-nginx."""

from py_manage_nginx.manager import list_sites, reload_nginx, restart_nginx, test_nginx_configuration
from py_manage_nginx.hosting import (
    create_hosting,
    remove_hosting,
    upload_source_archive,
)
from pathlib import Path
import shutil
import pytest
import os


# Absolute paths for demo static site assets used in the upload helper.
STATIC_SITE_DIR = Path(__file__).parent / "static_site"
SOURCE_CODE_HOSTING_DIR = Path(__file__).parent / "source_code_hosting"

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


def test_upload_source_archive(tmp_path):
    site_name = SITE_NAME
    archive_base = tmp_path / "static_site"
    shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=STATIC_SITE_DIR.parent,
        base_dir=STATIC_SITE_DIR.name,
    )
    archive = archive_base.with_suffix(".zip")

    if os.geteuid() == 0:
        web_root_base = Path("/var/www")
        document_root = web_root_base / site_name
        if document_root.exists():
            shutil.rmtree(document_root)
    else:
        web_root_base = tmp_path / "web"
        document_root = web_root_base / site_name

    # Seed document root with stale content to ensure the helper wipes it first.
    (document_root / "old-dir").mkdir(parents=True, exist_ok=True)
    (document_root / "old-dir" / "placeholder.txt").write_text("obsolete")
    (document_root / "legacy.txt").write_text("legacy")

    result_path = upload_source_archive(
        site_name,
        archive,
        web_root_base=web_root_base,
        remove_archive=True,
    )

    assert result_path == document_root
    assert (document_root / "index.html").is_file()
    assert (document_root / "assets" / "logo.svg").is_file()
    assert not (document_root / archive.name).exists()
    assert not (document_root / "legacy.txt").exists()
    assert not (document_root / "old-dir").exists()


def test_upload_source_archive_keep_archive(tmp_path):
    site_name = "keep-archive"
    archive_base = tmp_path / "static_site"
    shutil.make_archive(
        str(archive_base),
        "zip",
        root_dir=STATIC_SITE_DIR.parent,
        base_dir=STATIC_SITE_DIR.name,
    )
    archive = archive_base.with_suffix(".zip")

    web_root_base = tmp_path / "web"
    document_root = web_root_base / site_name

    result_path = upload_source_archive(
        site_name,
        archive,
        web_root_base=web_root_base,
        remove_archive=False,
    )

    assert result_path == document_root
    assert (document_root / "index.html").is_file()
    assert (document_root / archive.name).is_file()

def upload_static_site_to_sources(
    site_name: str = SITE_NAME,
    archive: Path | None = None,
    destination_base: Path = SOURCE_CODE_HOSTING_DIR,
) -> Path:
    """Convenience wrapper for syncing the demo site into a local folder."""

    destination_base.mkdir(parents=True, exist_ok=True)
    if archive is None:
        archive_base = destination_base / f"{site_name}_source"
        shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=STATIC_SITE_DIR.parent,
            base_dir=STATIC_SITE_DIR.name,
        )
        archive_path = archive_base.with_suffix(".zip")
    else:
        archive_path = Path(archive)

    return upload_source_archive(
        site_name,
        archive_path,
        web_root_base=destination_base,
        remove_archive=False,
    )
