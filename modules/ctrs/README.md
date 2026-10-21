# CTRs

Cost engineers draw up the CTRs for a job here and download them as one Excel workbook, a sheet per CTR laid out like
the company's CTR sheets, with a Summary sheet in front.

**Workbooks (estimates).** A workbook is the unit: it holds the project details once (client, project name and title,
framework ref) and the CTRs for the job. Starting one, you can tick the usual disciplines (Process, Piping, Instrument,
Electrical, Structural, Mechanical, Tech Safety, Construction, Surveys, Project Engineering) and get a CTR sheet for each;
more can be added, renamed, duplicated or deleted afterwards. The project details are copied onto every CTR in the
workbook when saved, so the sheets agree, and are changed on the workbook's page, not in a CTR. The workbook's Excel file
(`export.write_workbook`) is a Summary sheet (project details, then each CTR's hours and cost, and the totals) followed by
one sheet per CTR in creation order. The Summary's figures are formulas pointing at each CTR sheet's own total cells, which
the exporter writes, so a link cannot be left pointing nowhere. A single CTR can still be downloaded on its own.
**Hours from the jobcards, automatically.** A workbook can be linked to a jobcards workpack (only workpacks that have a
snapshot are offered). A sheet whose title is a discipline in `constants.DISCIPLINE_TRADES` (today, Piping, which takes
`P/Fitter`) then takes just those trades' hours from the newest snapshot of that workpack, when the workbook is made, when
such a sheet is added, when the workpack is first chosen, and whenever "Update hours from jobcards" is pressed. Each such
trade gets a resource named after it taking all of it, so the hours count at once and only the rate is left to type.
Updating replaces only those trades' earlier imported lines; other trades brought in by hand, typed lines and existing
resources are kept. The link is the workbook's `jobcards_workpack` (migration 0003). The jobcards module is reached only
through the `jobcards.hours` service, so everything here is skipped when it is not installed.

Not built yet: the phase-by-discipline roll-up with growth % that the company's Front Sheet has, and the non-labour pages.
Table `estimate` (migration 0002; CTRs that existed before it were gathered into a workbook per set of project details).

**What a CTR holds**
- Header (project, client, CTR no., prepared / checked / approved), objectives, input requirements.
- **Scope lines** with two hours columns (named "Eng" and "Design" by default, renamable). A line's hours are
  quantity x norm x factor, rounded up to a whole hour, or hours typed straight in. An **allowance** line is a percentage
  of every other line's hours. A line can have a **group** (a trade, say) that resources can take their hours from.
- **Resources**: each takes a typed percentage split of one source (a whole hours column, a group of lines, or hours
  typed in) and a typed rate per hour. Hours are shared out in whole numbers that add back up to the source
  (3 hours at 60/40 is 2 and 1), so the CTR always ties to the jobcards.
- **Additions** (offshore allowance, mob/demob), payment terms, basis of proposal.
- **Checks** (never blocking): splits not adding to 100%, hours no resource takes, hours shared out twice, a resource
  pointing at a group that no longer exists, resources with hours but no rate.

**Hours from the jobcards.** If the jobcards module is installed, a CTR can import a *snapshot* (frozen hours by trade)
through the `jobcards.hours` service: one scope line per trade, the trade as its group. The CTR records which snapshot
it came from and prints that under the scope table. Importing again replaces the earlier import and leaves typed lines.

**The Excel file** (`export.py`) is one A4 sheet. The printed part is columns A-J; beside the tables, outside the print area,
sit the working figures the original sheets keep there (factor, norms, each resource's split and source). Line hours,
resource costs and totals are formulas, with their results stored in the file so Protected View shows them. A resource's
hours are values (shared out by the tool), so change splits in the tool, not in the sheet. The logo is `assets/nmc-logo.png`.

The module never imports another module: the jobcards link is the optional service `jobcards.hours`.
