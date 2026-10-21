-- Which jobcards workpack (by its number) a workbook takes its hours from; blank means none.
ALTER TABLE estimate ADD COLUMN jobcards_workpack TEXT NOT NULL DEFAULT '';
