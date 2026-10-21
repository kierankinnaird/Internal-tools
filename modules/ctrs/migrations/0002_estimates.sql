-- An estimate is the workbook: the project details held once, and the CTRs (the sheets) inside it.
CREATE TABLE estimate (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  client TEXT NOT NULL DEFAULT '',
  project_name TEXT NOT NULL DEFAULT '',
  project_title TEXT NOT NULL DEFAULT '',
  framework_ref TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
ALTER TABLE ctr ADD COLUMN estimate_id INTEGER REFERENCES estimate(id) ON DELETE CASCADE;
CREATE INDEX ix_ctr_estimate ON ctr(estimate_id);

-- CTRs made before estimates existed: one estimate for each set of CTRs that share their project details.
INSERT INTO estimate (title, client, project_name, project_title, framework_ref, created_by, created_at, updated_by, updated_at)
SELECT CASE WHEN project_title <> '' THEN project_title WHEN project_name <> '' THEN project_name ELSE 'Estimate' END,
       client, project_name, project_title, framework_ref, MIN(created_by), MIN(created_at), MIN(updated_by), MAX(updated_at)
FROM ctr GROUP BY client, project_name, project_title, framework_ref;
UPDATE ctr SET estimate_id = (SELECT e.id FROM estimate e
                              WHERE e.client = ctr.client AND e.project_name = ctr.project_name
                                AND e.project_title = ctr.project_title AND e.framework_ref = ctr.framework_ref);
