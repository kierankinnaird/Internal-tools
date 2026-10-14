ALTER TABLE workpack ADD COLUMN workpacks_ref INTEGER;
CREATE INDEX ix_workpack_ref ON workpack(workpacks_ref);
