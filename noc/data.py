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

def _noc_source(code: str) -> str:
    return ("https://noc.esdc.gc.ca/Structure/NOCProfile"
            f"?GocTemplateCulture=en-CA&code={code}&version=2021.0")


# --- BC Tech dev/software NOCs -------------------------------------------------------
# Text below was transcribed from the official ESDC NOC profile page (raw page text, not a
# summary) on 2026-08-22. verified=False: a human still owes a line-by-line check against
# the source before these are trusted for a real audit (same posture as the SIRS bands).

NOC_21231 = NocOccupation(
    code="21231",
    title="Software engineers and designers",
    lead_statement=(
        "Software engineers and designers research, design, evaluate, integrate and maintain "
        "software applications, technical environments, operating systems, embedded software, "
        "information warehouses and telecommunications software. They are employed in "
        "information technology consulting firms, information technology research and "
        "development firms, and information technology units throughout the private and public "
        "sectors, or they may be self-employed."
    ),
    main_duties=[
        Duty("21231.1", "Collect and document users' requirements and develop logical and "
                        "physical specifications"),
        Duty("21231.2", "Research, evaluate and synthesize technical information to design, "
                        "develop and test computer-based systems including mobile applications"),
        Duty("21231.3", "Develop data, process and network models to optimize architecture and "
                        "to evaluate the performance and reliability of designs"),
        Duty("21231.4", "Plan, design and coordinate the development, installation, integration "
                        "and operation of computer-based systems including mobile applications"),
        Duty("21231.5", "Assess, test, troubleshoot, document, upgrade and develop maintenance "
                        "procedures for operating systems, communications environments and "
                        "applications software"),
        Duty("21231.6", "May lead and coordinate teams of information systems professionals in "
                        "the development of software and integrated information systems, process "
                        "control software and other embedded software control systems",
             optional=True),
    ],
    source=_noc_source("21231"),
    version="NOC 2021 Version 1.0",
    verified=False,
)

NOC_21232 = NocOccupation(
    code="21232",
    title="Software developers and programmers",
    lead_statement=(
        "Software developers and programmers design, write, and test code for new systems and "
        "software to ensure efficiency. They create the foundations for operative systems and "
        "run diagnostic programs to certify effectiveness. They are employed in computer "
        "software, computer and video game development firms, information technology consulting "
        "firms, and in information technology units throughout the private and public sectors."
    ),
    main_duties=[
        Duty("21232.1", "Design, write, read, test, and correct code for new software"),
        Duty("21232.2", "Analyze information to recommend and plan the installation of new "
                        "systems or modifications of an existing system"),
        Duty("21232.3", "Evaluate simple interrelationships between programs such as whether a "
                        "contemplated change in one part of a program would cause unwanted "
                        "results in a related part"),
        Duty("21232.4", "Program animation software to predefined specifications for interactive "
                        "video games, Internet and mobile applications"),
        Duty("21232.5", "Write, modify, integrate and test software code for e-commerce, "
                        "Internet and mobile applications"),
        Duty("21232.6", "Develop, implement, modify and maintain gameplay features that "
                        "integrate effectively into existing software"),
        Duty("21232.7", "Write documentation for new and updated software"),
    ],
    source=_noc_source("21232"),
    version="NOC 2021 Version 1.0",
    verified=False,
)

NOC_21230 = NocOccupation(
    code="21230",
    title="Computer systems developers and programmers",
    lead_statement=(
        "Computer systems developers and programmers write, modify, integrate and test computer "
        "code for software applications, data processing applications, operating systems-level "
        "software and communications software. They are employed in computer software "
        "development firms, information technology consulting firms, and in information "
        "technology units throughout the private and public sectors."
    ),
    main_duties=[
        Duty("21230.1", "Write, modify, integrate and test software code"),
        Duty("21230.2", "Maintain existing computer programs by making modifications as required"),
        Duty("21230.3", "Identify and communicate technical problems, processes and solutions"),
        Duty("21230.4", "Prepare reports, manuals and other documentation on the status, "
                        "operation and maintenance of software"),
        Duty("21230.5", "Assist in the collection and documentation of user requirements"),
        Duty("21230.6", "Assist in the development of logical and physical specifications"),
        Duty("21230.7", "May lead and coordinate teams of computer programmers", optional=True),
        Duty("21230.8", "May research and evaluate a variety of software products", optional=True),
    ],
    source=_noc_source("21230"),
    version="NOC 2021 Version 1.0",
    verified=False,
)

OCCUPATIONS: Dict[str, NocOccupation] = {
    NOC_21234.code: NOC_21234,
    NOC_21231.code: NOC_21231,
    NOC_21232.code: NOC_21232,
    NOC_21230.code: NOC_21230,
}


def get_occupation(code: str) -> NocOccupation:
    if code not in OCCUPATIONS:
        raise KeyError(f"NOC code not seeded: {code!r}. Add it to data.py from the official source.")
    return OCCUPATIONS[code]
