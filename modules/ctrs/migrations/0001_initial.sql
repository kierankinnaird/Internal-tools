CREATE TABLE ctr (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  ctr_no TEXT NOT NULL DEFAULT '',
  project_name TEXT NOT NULL DEFAULT '',
  project_title TEXT NOT NULL DEFAULT '',
  client TEXT NOT NULL DEFAULT '',
  ctr_date TEXT NOT NULL DEFAULT '',
  framework_ref TEXT NOT NULL DEFAULT '',
  prepared_by TEXT NOT NULL DEFAULT '',
  checked_by TEXT NOT NULL DEFAULT '',
  approved_by TEXT NOT NULL DEFAULT '',
  objectives TEXT NOT NULL DEFAULT '',
  inputs TEXT NOT NULL DEFAULT '',
  scope_intro TEXT NOT NULL DEFAULT '',
  scope_notes TEXT NOT NULL DEFAULT '',
  assumptions TEXT NOT NULL DEFAULT '',
  exclusions TEXT NOT NULL DEFAULT '',
  commencement TEXT NOT NULL DEFAULT '',
  completion TEXT NOT NULL DEFAULT '',
  duration TEXT NOT NULL DEFAULT '',
  expenses TEXT NOT NULL DEFAULT '',
  payment_terms TEXT NOT NULL DEFAULT 'Reimbursable',
  basis TEXT NOT NULL DEFAULT '',
  pool1_label TEXT NOT NULL DEFAULT 'Eng',          -- the two hours columns of the scope table
  pool2_label TEXT NOT NULL DEFAULT 'Design',
  source_snapshot_id INTEGER,                        -- the jobcards snapshot the hours were imported from, if any
  source_text TEXT NOT NULL DEFAULT '',              -- ...and what it was called then (kept even if the snapshot goes)
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE ctr_line (
  id INTEGER PRIMARY KEY,
  ctr_id INTEGER NOT NULL REFERENCES ctr(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'line',                 -- 'line', or 'allowance' (a percentage of all the other hours)
  description TEXT NOT NULL DEFAULT '',
  flag TEXT NOT NULL DEFAULT '',                     -- Activity / Deliverable column
  wbs TEXT NOT NULL DEFAULT '',
  grp TEXT NOT NULL DEFAULT '',                      -- a name resources can take their hours from (e.g. a trade)
  qty REAL,                                          -- for an allowance, the percentage
  eng_norm REAL,
  des_norm REAL,
  factor REAL,
  eng_override REAL,                                 -- typed hours, used instead of quantity x norm x factor
  des_override REAL,
  from_snapshot INTEGER NOT NULL DEFAULT 0           -- came from a jobcards snapshot import
);
CREATE TABLE ctr_resource (
  id INTEGER PRIMARY KEY,
  ctr_id INTEGER NOT NULL REFERENCES ctr(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'pool1',              -- 'pool1', 'pool2', 'group:<name>' or 'fixed'
  split_pct REAL NOT NULL DEFAULT 100,               -- share of the source's hours, in percent
  fixed_hours REAL,                                  -- hours typed in, when source is 'fixed'
  rate REAL                                          -- cost per hour, typed in
);
CREATE TABLE ctr_addition (
  id INTEGER PRIMARY KEY,
  ctr_id INTEGER NOT NULL REFERENCES ctr(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  unit_cost REAL,
  units REAL
);
CREATE INDEX ix_ctr_line_ctr ON ctr_line(ctr_id);
CREATE INDEX ix_ctr_resource_ctr ON ctr_resource(ctr_id);
CREATE INDEX ix_ctr_addition_ctr ON ctr_addition(ctr_id);
