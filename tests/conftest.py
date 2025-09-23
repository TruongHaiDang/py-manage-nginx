"""Test configuration helpers for loading the project package.

The source tree stores the project package in a directory containing hyphens.
Python module imports do not support that naming convention directly, so the
helper below registers the package under the canonical ``py_manage_nginx``
module name. Tests can then perform standard imports without dealing with the
unusual on-disk layout.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Resolve the root directory that contains the ``src`` tree.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PROJECT_ROOT / "src" / "py-manage-nginx"

if "py_manage_nginx" not in sys.modules:
    # Load the package dynamically so that submodules such as
    # ``py_manage_nginx.hosting`` can be imported normally.
    spec = importlib.util.spec_from_file_location(
        "py_manage_nginx",
        PACKAGE_DIR / "__init__.py",
        submodule_search_locations=[str(PACKAGE_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["py_manage_nginx"] = module
    assert spec.loader is not None  # Narrow the type for static checkers.
    spec.loader.exec_module(module)
