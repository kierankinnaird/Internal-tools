# Workpacks module

Fills the Apache certification forms (Word) for a workpack from details typed once into the web app. It replaces
the old way of working, which was a separate Excel input sheet and the Workpack Tools program.

## What it does

| Page | Who (permission) | What |
|---|---|---|
| Workpacks list | view | All workpacks, the state of the blank templates, create a workpack, import one from Excel (edit) |
| A workpack | view / edit | Project details (typed once, used by every form) and its certificates |
| A certificate | view / edit | The details for one form |
| Table rows | view / edit | The lines (SL1, MP1), joints (JI1) or tags (EE12) under a certificate, in a grid that takes pasted Excel cells |
| Fill forms | fill | Pick certificates, write the forms, see a result for each, download them as a zip |

Permissions: `workpacks.view`, `workpacks.edit`, `workpacks.fill`. People without `edit` get read-only pages and a 403 on
any change. Every change, fill, download and import is written to the audit log.

## Where things live

All under the app's data folder (`userdata/`, which git ignores). Nothing below is ever committed.

| Path | Holds |
|---|---|
| `workpacks.sqlite` | Workpacks, certificates and table rows (own migrations in `migrations/`) |
| `workpacks/templates/` | The blank Apache templates, installed from the templates pack. Set `NMC_WORKPACK_TEMPLATES` to use another folder |
| `workpacks/output/wp<id>/<run>/` | One folder per fill run: the forms, `fill-log.csv`, `fill-audit.csv` and `run.json` |

The Apache templates are Apache's documents, so they are not in the repository. The folder is checked against the pack's
`MANIFEST.csv` and the workpacks pages say if it is missing, incomplete or different from the pack. The templates are
only ever read; a test proves they are not modified by a fill.

## How a fill works

`fill.py` writes the engine's own blank input workbook (made by the engine) filled from the database, matching columns by
their header text, and runs the engine on it. The engine is not changed, so its checks and its output are exactly what the
old tool produced. A form that fails the engine's self-check is not offered for download.

## The engine

`engine/` is Workpack Tools **v2.3**, vendored unchanged. `tests/test_workpacks_engine.py` pins its files by SHA-256
(ignoring line endings), so a wrong or edited copy fails loudly.

To take a new release: copy `fill_workpack.py`, `fill_settings.json` and `CHANGELOG.md` over the ones in `engine/`, update
`VERSION` and `PINNED` in that test, and run `python -m pytest -q`. Another test checks that the labels the screens use are
the engine's labels, so a renamed column shows up straight away.

## Limits and safety

- Excel is import only (a new workpack from a Workpack Tools input workbook); nothing is exported to Excel.
- Import: `.xlsx` only, 5 MB, 500 certificates, 1000 rows per table. A bad workbook is refused whole and lists every problem.
- Table rows: 1000 per table; a post with mismatched columns is refused whole.
- Output folder and file names must be plain names; paths that leave the output folder are refused.
- Text starting with `=` is kept as text, never a formula.
- Run ids and download paths are checked, and a run can only be opened under its own workpack.

## Tests

```
python -m pytest tests/test_workpacks_*.py -q
```

Three tests fill real forms and skip themselves when the templates pack is not installed.