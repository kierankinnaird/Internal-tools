"""What a workpack, certificate and table row are made of: database column and the label people see.

The labels are the input sheet's own wording, so the screens and an imported workbook agree.
Column names here are the only ones ever put into SQL, and they never come from a user.
"""
from __future__ import annotations

WORKPACK_FIELDS = [
    ("title", "Project title"),
    ("project_no", "Project number (FCP)"),
    ("workpack_no", "Workpack number (Apache document / CCHP no)"),
    ("sh1_no", "SH1 number"),
    ("mc1_no", "MC1 number"),
    ("site", "Site"),
    ("location", "Default location"),
    ("system", "Default system"),
    ("subsystem", "Default sub-system"),
    ("handover_title", "Handover title (SH1 / MC1)"),
    ("handover_includes", "Handover includes (SH1 / MC1)"),
    ("handover_excludes", "Handover excludes (SH1)"),
    ("ee12_description", "Standard description of tests (EE12)"),
    ("nmc_cchp_no", "NMC CCHP number"),
    ("revision", "Revision"),
    ("cover_title", "Cover title"),
    ("jre", "Responsible engineer (JRE)"),
    ("cchp_title", "CCHP checklist title"),
]

CERTIFICATE_FIELDS = [
    ("filename", "Output file name (optional)"),
    ("equipment", "Equipment / line"),
    ("location", "Location"),
    ("area", "Area"),
    ("system", "System"),
    ("subsystem", "Sub-system"),
    ("drawing", "Drawing / P&ID / SLD"),
    ("description", "Equipment description"),
    ("scope", "Scope of certificate"),
    ("procedure", "Commissioning procedure text"),
    ("ee12_description", "Description of tests (EE12 override)"),
    ("punch_no", "Punch list number"),
    ("discipline", "Discipline"),
    ("folder", "Output folder (optional)"),
    ("sl1a", "SL1A request no"),
    ("hdr_title", "Header: project title"),
    ("hdr_site", "Header: site"),
    ("hdr_mc1_no", "Header: MC1 number"),
]

# kind -> (table, [(column, label), ...]). SL1 and MP1 use "line", JI1 uses "joint", EE12 uses "tag".
ROW_KINDS = {
    "line": ("line", [("pid", "P&ID No / ISO No"), ("line_no", "Line No"),
                      ("from_equipment", "From equipment"), ("to_equipment", "To equipment")]),
    "joint": ("joint", [("joint_no", "Joint number"), ("drawing", "Drawing"), ("size", "Flange size (NB)"),
                        ("rating", "Rating"), ("joint_type", "Type"), ("torque", "Required torque value")]),
    "tag": ("tag", [("tag", "Tag"), ("drawing", "Drawing No.")]),
}

# Which table rows a form takes. Forms not listed here have no table.
ROW_KIND_BY_FORM = {"SL1": "line", "MP1": "line", "JI1": "joint", "EE12": "tag"}

WORKPACK_COLUMNS = [c for c, _ in WORKPACK_FIELDS]
CERTIFICATE_COLUMNS = [c for c, _ in CERTIFICATE_FIELDS]