"""The MapleGuard MCP server (mcp_app.py) exposes the deterministic core as MCP tools.

Offline: imports the FastMCP app and calls the tool functions directly (FastMCP's @tool returns the
original callable). Skipped when the mcp SDK is absent, so the rest of the suite stays green on a
machine without it.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_mcp_app.py
"""
import asyncio

import pytest

_PROFILE = {"age": 30, "education": "masters-or-professional",
            "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
            "noc_code": "21231"}


def _app():
    pytest.importorskip("mcp")
    import mcp_app
    return mcp_app


def test_server_registers_the_five_deterministic_tools():
    app = _app()
    names = {t.name for t in asyncio.run(app.mcp.list_tools())}
    assert {"compute_crs", "eligible_pathways", "crs_trajectory", "crs_deadlines",
            "noc_occupation"} <= names


def test_tools_return_cited_deterministic_results():
    app = _app()
    assert isinstance(app.compute_crs(_PROFILE)["total"], int)
    pw = app.eligible_pathways(_PROFILE)
    assert len(pw["pathways"]) >= 12                      # general + 10 categories + 11 PNPs
    assert all(p["source_url"].startswith("http") for p in pw["pathways"])
    occ = app.noc_occupation("21231")
    assert occ["source"].startswith("http") and occ["main_duties"]
