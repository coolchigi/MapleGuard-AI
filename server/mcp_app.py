"""MapleGuard MCP server: the deterministic, cited immigration tools as a standard MCP endpoint.

This is the tool surface, exposed over the Model Context Protocol so any MCP client (our own agent
team, Claude Desktop, a settlement agency's assistant) consumes the SAME cited numbers the engine
computes. Determinism below the model, made interoperable.

Hosting: Amazon Bedrock AgentCore Runtime, `agentcore configure --protocol MCP` + `agentcore
launch`. AgentCore's contract is a stateless streamable-HTTP MCP server on 0.0.0.0:8000/mcp, which
is exactly the FastMCP defaults set below (verified against the mcp SDK and the AgentCore docs).

Only the pure, deterministic core is exposed here (crs / paths / pnp / ingest / noc via `serde`),
no model call, so the server has no way to invent a number. The model-backed NOC audit stays in the
agent layer. Every tool returns the cited dict the deterministic core produces (each value carries
its government source).

Run locally:  cd server && python3 mcp_app.py      # serves http://0.0.0.0:8000/mcp
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

# host/port/path and stateless mode are the AgentCore Runtime MCP contract.
mcp = FastMCP("mapleguard", host="0.0.0.0", port=8000, stateless_http=True)


@mcp.tool()
def compute_crs(profile: dict, as_of: Optional[str] = None) -> dict:
    """Compute a candidate's Comprehensive Ranking System (CRS) score from the published IRCC grid.

    Returns the total, the four block subtotals, and the per-factor breakdown, each a value read
    from the cited government grid. `profile` is the candidate profile (education, first_language
    CLB per ability, age or date_of_birth, work years, nomination flags, ...). `as_of` is an
    optional ISO date to score as of (age is date-dependent).
    """
    from agent import serde
    from crs import crs
    p = serde.profile_from_dict(profile)
    return serde.score_to_dict(crs(p, serde._parse_date(as_of)))


@mcp.tool()
def eligible_pathways(profile: dict, as_of: Optional[str] = None) -> dict:
    """What the candidate qualifies for across every Express Entry pathway and all 11 provincial
    nominee programs, each with its cited eligibility verdict. Surfaces options a candidate would
    not know to look for (the French category, a provincial program). `as_of` is an optional ISO
    date. Occupation-category checks use the profile's noc_code when present.
    """
    from agent import serde
    from paths import eligible_pathways as _eligible_pathways
    p = serde.profile_from_dict(profile)
    return _eligible_pathways(p, as_of=serde._parse_date(as_of)).to_dict()


@mcp.tool()
def crs_trajectory(profile: dict, start: str, end: str) -> dict:
    """Plot the candidate's CRS across a date range, with each dated cliff labelled (an age-bracket
    drop, a language-test expiry). The time-machine data. `start`/`end` are ISO dates and the
    profile needs a date_of_birth.
    """
    from agent import serde
    from crs.timeline import trajectory as _trajectory
    p = serde.profile_from_dict(profile)
    return serde.trajectory_to_dict(_trajectory(p, serde._parse_date(start), serde._parse_date(end)))


@mcp.tool()
def crs_deadlines(profile: dict, as_of: Optional[str] = None) -> dict:
    """The dated cliffs ahead for the candidate: the next age-bracket step-down and any language
    test expiry, each with the CRS it costs. `as_of` is an optional ISO date; the profile needs a
    date_of_birth.
    """
    from agent import serde
    from crs.timeline import deadlines as _deadlines
    p = serde.profile_from_dict(profile)
    return serde.deadlines_to_dict(_deadlines(p, serde._parse_date(as_of)))


@mcp.tool()
def noc_occupation(noc_code: str) -> dict:
    """The cited NOC 2021 occupation for a five-digit code: its lead statement and main duties, with
    the canada.ca source. Use it to see the official duty text a reference letter is judged against.
    """
    from noc import get_occupation
    occ = get_occupation(noc_code)
    return {
        "noc_code": occ.code,
        "title": occ.title,
        "teer": occ.teer,
        "lead_statement": occ.lead_statement,
        "main_duties": [{"id": d.id, "text": d.text, "optional": d.optional}
                        for d in occ.main_duties],
        "source": occ.source,
        "version": occ.version,
        "verified": occ.verified,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
