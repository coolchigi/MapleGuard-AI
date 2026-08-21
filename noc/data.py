"""Seeded NOC 2021 occupations.

Lead statements and main duties are transcribed verbatim from the official ESDC NOC
profile pages. Each occupation records its source URL and version. Additional codes are
added the same way: copy the lead statement and the "Main duties" list exactly, mark
duties phrased as "May ..." as optional, and set verified=True after checking the text
against the source.
"""
from __future__ import annotations

from typing import Dict

from .models import Duty, NocOccupation

_NOC_21234_SOURCE = ("https://noc.esdc.gc.ca/Structure/NOCProfile"
                     "?GocTemplateCulture=en-CA&code=21234&version=2021.0")

NOC_21234 = NocOccupation(
    code="21234",
    title="Web developers and programmers",
    lead_statement=(
        "Web developers and programmers use a variety of programming languages to design, "
        "create and modify Web sites. They analyze users' needs to implement content, "
        "graphics, performance, and Web site capacity. They may also integrate Web sites "
        "with other computer applications."
    ),
    main_duties=[
        Duty("21234.1", "Develop, write, modify, integrate and test Web site related code "
                        "and Web application interfaces"),
        Duty("21234.2", "Conduct tests and analyze data to monitor quality, security, user "
                        "interface experiences and to identify areas for improvement"),
        Duty("21234.3", "Develop and implement procedures for ongoing Web site revision"),
        Duty("21234.4", "Monitor and maintain Web site functionality"),
        Duty("21234.5", "May participate in Web site architecture and design in collaboration "
                        "with designers or clients", optional=True),
        Duty("21234.6", "May research and evaluate a variety of interactive media software "
                        "products", optional=True),
    ],
    source=_NOC_21234_SOURCE,
    version="NOC 2021 Version 1.0",
    verified=True,
)

OCCUPATIONS: Dict[str, NocOccupation] = {
    NOC_21234.code: NOC_21234,
}


def get_occupation(code: str) -> NocOccupation:
    if code not in OCCUPATIONS:
        raise KeyError(f"NOC code not seeded: {code!r}. Add it to data.py from the official source.")
    return OCCUPATIONS[code]
