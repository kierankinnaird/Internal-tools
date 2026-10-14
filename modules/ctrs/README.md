# CTRs

Cost engineers draw up a CTR here and download it as an Excel sheet laid out like the company's CTR sheets.

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
