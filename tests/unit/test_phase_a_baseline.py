"""Phase A baseline checks for the seldon rename and compatibility surface."""
from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


def test_seldon_public_import_surface():
    seldon = importlib.import_module("seldon")

    assert seldon.__version__ == "0.1.0"
    assert hasattr(seldon, "SeldonClient")
    assert hasattr(seldon, "SeldonConfig")
    assert "SeldonClient" in seldon.__all__
    assert "SeldonConfig" in seldon.__all__


def test_project_metadata_uses_seldon_name():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "seldon"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/seldon"]
    assert "The Seldon Project" in pyproject["project"]["description"]
    assert "Parallax" not in pyproject["project"]["description"]


def test_readme_documents_seldon_package_and_product_name():
    readme = Path("README.md").read_text()

    assert "**The Seldon Project**" in readme
    assert "`seldon`" in readme
    assert "`intelligence`" not in readme
