"""Tests for the upload_hosting_source helper."""

from pathlib import Path

import pytest

from py_manage_nginx.hosting import upload_hosting_source


def test_upload_hosting_source_directory(tmp_path: Path) -> None:
    """Uploading a directory should clean the destination and copy contents."""

    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
    assets = source / "assets"
    assets.mkdir()
    (assets / "style.css").write_text("body{color:black}", encoding="utf-8")

    destination = tmp_path / "hosting"
    destination.mkdir()
    (destination / "old.txt").write_text("stale", encoding="utf-8")

    resolved_destination = upload_hosting_source(source, destination)

    assert resolved_destination == destination.resolve()
    assert not (destination / "old.txt").exists()
    assert (destination / "index.html").read_text(encoding="utf-8") == "<h1>Hello</h1>"
    assert (destination / "assets" / "style.css").read_text(encoding="utf-8") == "body{color:black}"


def test_upload_hosting_source_file(tmp_path: Path) -> None:
    """Uploading a single file should place it inside the hosting directory."""

    source_file = tmp_path / "package.zip"
    source_file.write_bytes(b"PK\x03\x04")

    destination = tmp_path / "hosting"
    resolved_destination = upload_hosting_source(source_file, destination)

    assert resolved_destination == destination.resolve()
    copied = destination / source_file.name
    assert copied.is_file()
    assert copied.read_bytes() == b"PK\x03\x04"


def test_upload_hosting_source_overlap(tmp_path: Path) -> None:
    """Uploading into an overlapping path should raise a descriptive error."""

    source = tmp_path / "source"
    source.mkdir()
    destination = source / "nested"
    destination.mkdir()

    with pytest.raises(ValueError):
        upload_hosting_source(source, destination)
