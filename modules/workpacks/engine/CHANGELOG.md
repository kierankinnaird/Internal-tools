# Workpack Tools: version history

Newest first. Packaged copies of each release are in `releases/` (one folder per version, with SHA-256 fingerprints in `releases/README.md`). The version number lives in one place, `VERSION` in `fill_workpack.py`; it shows in the menu title, `WorkpackTools --version`, and the `tool version` column of `fill-log.csv`.

When you change the tool: raise `VERSION` (and the numbers in `dev/exe_version_info.txt`), add an entry here, run `dev/test_fill.py`, rebuild the exe (command in `analysis/HANDOFF-NOTES.md` section 9), package into `releases/`.

---

## v2.3, 2026-10-07

Fifth release. Adds the CCHP completion checklist (C1) and a blank workpack master (DM) to what the tool fills.

**Added**
- **CCHP completion checklist (form `C1`, Apache ANS-PRO-225_3rev5).** Put `C1` in the Form column and the tool fills the identification block: FCP number, responsible engineer (JRE), document number (the workpack number), SH1 number, title. Everything else on the form (Y/N, actionee, person, date, comments) stays blank for people. Output goes to `0.0 CCHP CHECKLIST`.
- **Form `DM` fills the workpack master's identification values** (v2.3): cover text boxes (site, cover title, Apache doc no, FCP, SH1, revision; the drawing and its fallback copy), the cover table (title, CCHP, SH1, FCP), the revision cell and the page header (SH1, CCHP, NMC CCHP, FCP, Rev). Output goes to `1.0 SCOPE OF WORK`. Dates, initials, descriptions, contents tables, the drawing register and the scope text are never filled. Three new optional Project rows: `NMC CCHP number`, `Revision`, `Cover title` (blank = project title). Filled from the WPK-016 sheet it matches the pack's own cover text, cover table and page header exactly (T44 to T44e).
- **Two new optional Project rows for the checklist**: `Responsible engineer (JRE)` and `CCHP checklist title` (the checklist's wording differs from the form-header title, e.g. "... FOR SLOT BB-18"; blank = project title). Older input sheets work without them.
- **`templates\C1 CCHP.docx`**: Apache's guidance folder has no blank checklist, so it is derived from the pack's own (the five values blanked, every other byte identical, checked by `dev/build_template_bundle.py`). The manifest says so.
- **`templates\DM Workpack Master.docx`: a blank workpack master (cover, revision table, contents, scope of work, foreword, section 2.0 to 10.0 tables, drawing register).** Apache has no template for it (the packs' authors start from `wpmast.dot` on a network drive that is not available), so it is derived from the WPK-016 master by `dev/build_dm_template.py`, then `dev/update_fields.ps1` refreshes the contents list in Word. Project values, tags, drawing numbers and the two named contacts are gone; the scope of work has two grey bracketed FREE TEXT areas (scope description; work by discipline) around "usual wording" that was identical in packs 016, 017 and 019 (hydraulic isolations, software / C&E note, site rules); the commissioning foreword is kept word for word (the construction lead marked it as never changing) with a note to delete the leak-testing block when there are no leak tests; tables keep their headings and have empty rows; the drawing register keeps its six group headings. Not filled by the tool yet (hand use). Bundle is now 75 files.
- **Release steps used:** exe built in the clean venv (`--exclude-module PIL --exclude-module lxml.isoschematron`), 70 of 70 tests, packaged with `dev/package_release.py` (now skips Office `~$` lock files), the Word guide patched by `dev/patch_user_guide.py` (version, zip name, two sentences, two project-detail rows, C1 and DM rows; all other parts byte-identical), START HERE updated. The exe, run with Python off the path on the practice sheet, made all 6 forms (SH1, MC1, 2 x AS1, C1, DM) byte-identical to the Python version's. exe SHA-256 `1468666A...1E8A`.
- Example sheets: `Blank input sheet.xlsx` regenerated with the five new Project rows; the practice sheet gains made-up values for them and a `C1` and a `DM` row (fills with no problems).
- 22 new tests in all (70 in total, T37 to T46): the checklist ones below, T42 to T43d for the master, T44 to T46 for filling it (same headings and tables as the pack, foreword identical, no project value / name / e-mail / mailto link, no author in the properties, free-text areas present, YES / NO not pre-filled).
- (earlier count) 9 new tests (57 in total): the template differs from the pack's only in the five cells and carries no project value; filled output matches the WPK-016 and WPK-017 checklists in all 140 cells; formatting; blank JRE; refusal to overwrite typed text.

**Note**
- The form has no MC1 number box (the header block holds FCP, JRE, document number, SH1 number, title).
- Not yet done for release: README/guide wording (73 templates, list of nine body-mapped forms), `START HERE`, rebuild and package.

---

## v2.2, 2026-10-07

Fourth release. The blank boxes in the form headers get their labels and numbers, and one v2.1 slip is fixed.

**Added**
- **The blank boxes in the form headers are now labelled and filled.** Apache's templates leave one or two empty, unlabelled boxes under the SH1 / System / PO line of the header (they are editable in the protected form). The pack authors typed `WPK No:` and `MC1 No:` into them by hand; the tool now does the same. Applies to 7 forms (the only ones with such boxes among the 68 Word templates): SH1 (`WPK No`, `MC1 No`), MC1 (`WPK No`; its own `MC1 No` box is already in the template), NP1, PC1, PP1 (`WPK No`, `MC1 No`), SS1 and IRN (`WPK No`). The values come from the Project sheet (`Workpack number`, `MC1 number`; a certificate's own `Header: MC1 number` wins). A box is labelled even when the sheet has no value for it (the log says so), and a label is skipped if the form already has one.
- **The 7 bundled templates now carry those labels**, so people filling the blank forms by hand get the same boxes. Only one header part of each file changes (checked: protection settings, editing-permission markers and every other part stay byte-identical to Apache's original), made by `dev/build_template_bundle.py` from Apache's originals, which are never written to. The other 66 bundled templates are still byte-identical copies.
- **`MANIFEST.csv` has two new columns**, `labelled header boxes` and `apache original sha256`. The template check in `fill-log.csv` has a new result, **`matches Apache original`**: Apache's own file chosen with `--templates` is recognised and is not reported as `DIFFERS from bundled`. The tool labels the boxes itself when they are still blank, and the forms come out byte-identical either way (tested).
- **`header_extra_rows` in the settings file** controls which labels go into which form's blank boxes, in order, with the project value each takes. `[]` leaves a form alone. The defaults are built in, so the share package works without a settings file.
- The self-check accepts a label only in a header box that was blank in the template.
- The user guide (Word and Markdown) is updated to v2.2 and says what the labelled boxes are.
- 11 new tests (48 in total): T20b, T29 to T36.

**Fixed**
- **`fill-audit.csv` was never written** (v2.1 returned before writing it, although the guide and README say it is produced). It is written again, next to `fill-log.csv`.
- The settings loader now ignores `_note` entries inside `header_extra_rows`, as it does in the other sections.

**Note**
- SH1 and MC1 follow the real WPK 016 / 017 packs. NP1, PC1, PP1, SS1 and IRN do not appear in either pack (only Apache's blank templates), so their labels are a proposal; change them in `header_extra_rows` if Apache or the team want different wording. On MC1 the pack puts `WPK No` above `MC1 No`; the template already has `MC1 No` first, so the tool adds `WPK No` below it.
- This resolves open question 25 for Alex in the direction Kieran was given permission to take (labelling the blank boxes).
- Body boxes (as opposed to the header block) were not surveyed.

---

## v2.1, 2026-10-05

Third release. Aimed at ordinary users: nothing to set up, nothing technical to answer, Apache's templates included, and NMC Energy branding. The workpack validator is removed.

**Added**
- **Apache's blank templates come with the tool.** A `templates` folder (73 files: 68 Word, 5 Excel) next to the tool, copied byte for byte from `ANS-TI-019_Guidance_on_Certification` and flattened so paths stay short. Users no longer need a local copy. The templates are still never edited: the tool refuses an output folder inside them, and the bundled copies are identical to Apache's (tested).
- **`templates\MANIFEST.csv`:** SHA-256, size, editing-protected yes/no and footer revision text for every template.
- **Template check in the log:** `fill-log.csv` has new columns `template` and `template check` (`matches bundled`, `DIFFERS from bundled`, `not in bundled set`). The console prints a note when a template differs from the bundled one. The forms are still filled.
- **`--templates` is now optional** (for a different set, such as a newer Apache revision). The file picker skips the templates step when the bundled set is present.
- **NMC Energy branding** (taken from nmcenergy.com): the NMC wordmark and brand colours on the menu, the NMC icon on the window and on `WorkpackTools.exe`, Windows file properties (company NMC Energy, product NMC Workpack Tools, version 2.1), NMC blue and title on the generated input sheet and the example sheets, and an NMC header line in the console. The forms that are produced carry no branding: they are Apache's forms.
- **Last-used folders are remembered** by the pickers, and the output picker starts next to the input sheet.
- **A lean package to share with end users:** `NMC Workpack Tools v2.1.zip` holds only what a user needs: `WorkpackTools.exe` and its support folder, Apache's templates, the logo files, two example sheets (a blank one and `Practice sheet (made-up project).xlsx`), a one-page `START HERE.txt` and the Word user guide (`Workpack Tools - User Guide.docx`). No source code, settings file, changelog, technical README or the example sheets built from real packs. It unpacks straight into one folder (no folder inside a folder). A separate `WorkpackTools-v2.1-support.zip` holds the source and everything else for whoever supports the tool. `dev/package_release.py` builds both.
- **Practice sheet:** a made-up project (nothing real in it) for a first try; its first tab says it is a practice sheet.
- **User guide** for non-technical users: `docs/Workpack Tools - User Guide.docx` (9 pages, NMC styling, six pictures from a made-up project) ships in the share zip. Its Markdown source and the brief used to produce it stay in `docs/` and are not shipped.
- `dev/build_template_bundle.py` refreshes the templates folder and manifest; `dev/build_brand_assets.py` rebuilds the branding files from `dev/brand/`.
- 11 new tests (37 in total).

**Removed**
- **The workpack validator** (menu item 2, `validate` command, `--validate` option, and the "check afterwards" question). Reasons: the team proof-reads every pack anyway, and on a second project it produced errors that were one finding repeated. The source is kept in `dev/archive/` as a reference for a rewrite (not shipped). v1.0 and v2.0 still contain it. Dropping it also removes the PDF library (`pypdf`) from the requirements.
- **The spare-rows question** in the picker. The default is to leave the template's rows; `output.spare_rows` in the settings file or `--spare-rows N` still trim them.

**Fixed**
- The console line `Settings:` was missing a space.

**Results**
- 37 of 37 safety tests pass; all 73 template files and the bundled copies are unchanged by every test.
- Filling WPK 017 through the bundled templates gives forms byte-identical to filling from Apache's own folder; the program version's 23 forms for WPK 017 are byte-identical to the Python version's, with Python off the path.
- WPK 016: 1,856 of 1,876 cells match the pack's forms. WPK 017: 1,950 of 1,976, plus the 8 leak-test certificates match the pack's PDFs on page 1.
- The share zip's longest path is 52 characters, so it extracts cleanly even deep inside other folders (Windows' limit is 260).
- The exe is built in a clean environment holding only lxml and openpyxl (an earlier build of v2.1 had bundled an unused imaging library by accident). It runs with Python off the path.
- Program version SHA-256: `CCD1AC43A16FB899E033FAB4E594F321E4E94C983AFEE54779E5FFF6A1908A5A`

**Known limits (unchanged)**
- Body fields are mapped for 9 forms only; the other 59 templates get a header only.
- The pack's added "WPK No" header row on SH1, MC1 and PL1 is not added; open question 25 for Alex.
- Excel forms (EE18, ITR index), the CCHP checklist, the scope-of-work document and the SL1A request form are not produced.
- Only MC1 was checked for template sample text.
- The packages are larger because the templates are included: the share zip is about 53 MB (v2.0: 19 MB) and the support zip about 35 MB (v2.0: under 0.1 MB). Too big for most email attachments; share it on a drive.
- The program is unsigned; Windows or security software may ask to approve it.

---

## v2.0, 2026-10-05

Second release. Built after testing the tool on a second workpack (WPK 017 BB20) and finding what it could not do. The form filler is the focus; the validator is unchanged apart from one line (see "Changed").

**Added**
- **Settings file** `fill_settings.json` (next to the tool or exe, or `--settings FILE`). All keys optional. Sets the output folder for each form, the default file name pattern, per-form spare-row trimming, sample text to blank, and extra header label spellings. A mistake in the file stops the run and lists every problem. The tool prints which settings it used.
- **New Certificates columns** in the input sheet: `SL1A request no`, and `Header: project title`, `Header: site`, `Header: MC1 number` (this certificate's header only). Older input sheets still work; the columns are simply blank.
- **SL1A request number**: replaces the template's `SL1A-XX-XXXXX` in the SL1 SCOPE OF TEST, including when the template splits it across runs.
- **Version number** in the menu title, `--version`, `--selftest` and `fill-log.csv`.
- **Example sheet for WPK 017** (`examples/`), including the 8 leak-test certificates.
- 12 new safety tests (26 in total).

**Fixed**
- **Template sample text left in output.** Apache's blank MC1 carries a sample punch list number `P-1121`; v1.0 copied it into every MC1. It is now blanked (configurable), before anything is typed, so a value you supply is never blanked.
- **`--spare-rows` could reject MP1** with "bookmarks changed". Word's hidden `_GoBack` bookmark is now ignored by the safety check.
- **"Path too long" when unzipping the program version.** The program folder contained lxml's unused Schematron stylesheets (`lxml\isoschematron\resources\...`), whose long names pushed the full path past Windows' 260-character limit when the zip was extracted into a deeply nested folder (Explorer error 0x80010135). They are no longer bundled (`--exclude-module lxml.isoschematron`). The longest path inside the program zip is now 90 characters, so it extracts cleanly even inside the workpack folder. (v1.0 also contained them; extract v1.0 to a short folder such as the Desktop.)
- The README described a difference in the 016 comparison wrongly ("a human-typed YES on MC1"). It was the sample punch list number above.

**Changed**
- The picker no longer asks about spare rows when the settings file sets them.
- The validator skips any folder starting with `WorkpackTools` (the tool now sits inside the pack folder, and its example sheets were being scanned). No other validator change.
- Developer scripts in `dev/` find the pack as the parent folder of `WorkpackTools/`, or from the `WPK_PACK` environment variable.

**Results**
- WPK 016: 1,856 of 1,876 cells match the pack's own forms (v1.0: 1,855).
- WPK 017: 15 Word forms, 1,950 of 1,976 cells match; the 8 leak-test certificates match the pack's PDFs character for character on page 1.
- 26 of 26 safety tests pass; all 73 template files unchanged afterwards.
- exe run with Python off the path; its 23 forms for WPK 017 were byte-identical to the Python version's.
- Program version SHA-256: `D9541970B7FBBE3CACCB7C9F440A54EAEE981C4E6B282C8756B253FE8F5B3521`

**Known limits (unchanged)**
- Body fields are mapped for 9 forms only; the other 59 templates get a header only.
- The pack's added "WPK No" header row on SH1, MC1 and PL1 is not added (16 differing cells per pack); open question 25 for Alex.
- Excel forms (EE18, ITR index), the CCHP checklist, the scope-of-work document and the SL1A request form are not produced.
- Only MC1 was checked for template sample text; the other templates were not.
- Validator gaps found on 017 were not worked on (the DM file is found only by a name starting `DM-`; PDFs over 1.5 MB are skipped without a message). See `analysis/second-pack-017-validation.md`.

---

## v1.0, 2026-10-02

First release. One menu with a form filler and a read-only validator.

**Included**
- Form filler driven by one input workbook (sheets Project, Certificates, Lines, Joints, Tags). Header block on every template; body fields for SH1, MC1, PL1 A/B, AS1, EE12, SC1, SL1, MP1, JI1.
- Safety checks on every form written: templates never modified, output folder kept separate, label check before writing, existing text never overwritten, protection settings identical, bookmarks unchanged, only intended cells changed; failed forms renamed `.REJECTED`; `fill-log.csv` and `fill-audit.csv`.
- Validator for a workpack (headers, counts, hours, drawings, tags) and a blank input sheet generator.
- Program version for computers without Python (PyInstaller).

**Results**
- WPK 016: 1,855 of 1,876 cells match the pack's own forms; 14 of 14 safety tests pass; the validator found 0 errors on the pack and caught six planted errors.
- Program version SHA-256: `C9D8CBB185E876D7D530B01CF094BF15B61EB1A170151A972903415830F5C397`

**Problems found later (fixed in v2.0)**
- MC1 sample punch list number `P-1121` copied into output.
- `--spare-rows` could reject MP1 (`_GoBack` bookmark).
- No way to give one certificate its own header title, site or MC1 number, and no SL1A request number.

**Before v1.0**
- Early validator-only packages (`analysis/WorkpackValidator.zip`, `WorkpackValidator-NoPython.zip`) predate a fix to how Word files are read (some templates name their main part `document2.xml`). They are superseded by v1.0 and should not be used.
