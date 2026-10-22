"""Regression: text files must be read and written as UTF-8 on every OS.

Windows defaults to the cp1252 code page, so `Path.read_text()` without an encoding fails on
UTF-8 files such as dashboard.js (curly quotes) while passing on macOS/Linux. This guards every
Python file in the backend and the search bridge.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(p for folder in ("backend", "search_engine") for p in (ROOT / folder).rglob("*.py")
                 if not {".venv", "__pycache__"} & set(p.parts))


def _text_io_without_encoding(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or "encoding" in {k.arg for k in node.keywords}:
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in ("read_text", "write_text"):
            found.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}()")
        elif name == "open" and isinstance(node.func, ast.Name):
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            mode = mode.value if isinstance(mode, ast.Constant) else "r"
            if "b" not in str(mode):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno} open({mode!r})")
    return found


def test_sources_were_found():
    assert len(SOURCES) > 20


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_text_file_io_names_its_encoding(path):
    assert _text_io_without_encoding(path) == []


def test_dashboard_script_is_utf8_with_non_ascii_text():
    # The original failure: this file contains non-cp1252-safe UTF-8 and must load on Windows.
    raw = (ROOT / "backend/tanya/static/dashboard.js").read_bytes()
    assert any(b > 127 for b in raw)
    raw.decode("utf-8")
