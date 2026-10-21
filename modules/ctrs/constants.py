"""Fixed lists and starting text for a CTR."""

PAYMENT_TERMS = ["Reimbursable", "Budget", "Lump Sum"]
FLAGS = ["", "A", "D"]                                  # the Activity / Deliverable column

# The header fields of the CTR sheet, in the order they appear: (column, label).
HEADER_FIELDS = [
    ("project_name", "Project name"), ("project_title", "Project title"), ("client", "Client"),
    ("ctr_date", "Date"), ("framework_ref", "Framework agreement ref"),
    ("title", "CTR title"), ("ctr_no", "CTR no."),
    ("prepared_by", "Prepared by"), ("checked_by", "Checked by"), ("approved_by", "Approved by"),
]
TEXT_FIELDS = ["objectives", "inputs", "scope_intro", "scope_notes", "assumptions", "exclusions",
               "commencement", "completion", "duration", "expenses", "basis", "pool1_label", "pool2_label"]
SIMPLE_FIELDS = [c for c, _ in HEADER_FIELDS] + TEXT_FIELDS
LONG_FIELDS = {"objectives", "inputs", "scope_notes", "assumptions", "exclusions", "basis"}    # the rest are one line
FIELD_LABELS = dict(HEADER_FIELDS)
FIELD_LABELS.update(objectives="Objectives", inputs="Input requirements", scope_intro="Scope heading",
                    scope_notes="Scope notes", assumptions="Assumptions", exclusions="Exclusions",
                    commencement="Commencement date", completion="Completion date", duration="Duration",
                    expenses="Expenses", basis="Basis of proposal", pool1_label="First hours column",
                    pool2_label="Second hours column")

# What a workbook (an estimate) holds once for all of its CTRs: (column, label). The last four are shown on every CTR
# sheet and kept the same on all of them.
ESTIMATE_FIELDS = [("title", "Estimate name"), ("client", "Client"), ("project_name", "Project name"),
                   ("project_title", "Project title"), ("framework_ref", "Framework agreement ref")]
SHARED_FIELDS = ["client", "project_name", "project_title", "framework_ref"]
# The CTRs the company's cost workbook usually holds, one sheet each; offered when an estimate is started.
DISCIPLINES = ["Process", "Piping", "Instrument", "Electrical", "Structural", "Mechanical", "Tech Safety",
               "Construction", "Surveys", "Project Engineering"]

# The jobcard trades a discipline's CTR takes its hours from, automatically, when its workbook is linked to a jobcards
# workpack. A CTR is matched by its title being the discipline's name. Other trades can always be brought in by hand.
DISCIPLINE_TRADES = {"Piping": ["P/Fitter"]}

# What a new CTR starts with. All of it can be changed or removed.
DEFAULT_SCOPE_INTRO = "This CTR covers the following key deliverables / activities:"
DEFAULT_ASSUMPTIONS = "This CTR assumes the following:\n- "
DEFAULT_EXCLUSIONS = "This CTR excludes the following:\n- "
DEFAULT_BASIS = "1. All personnel rates will be subject to VAT."
DEFAULT_ADDITIONS = ["Offshore Allowance", "Mob / De-Mob Travel Allowance"]
DEFAULT_POOLS = ("Eng", "Design")

# Limits on what one CTR may hold, so a bad request cannot make a huge file.
MAX_LINES = 400
MAX_RESOURCES = 60
MAX_ADDITIONS = 30
MAX_TEXT = 20000
MAX_CTRS = 60                   # in one workbook
