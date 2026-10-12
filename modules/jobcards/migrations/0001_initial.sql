CREATE TABLE workpack (
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  asset TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  discipline TEXT NOT NULL DEFAULT '',
  ces_doc_no TEXT NOT NULL DEFAULT '',
  jobcard_prefix TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE jobcard (
  id INTEGER PRIMARY KEY,
  workpack_id INTEGER NOT NULL REFERENCES workpack(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  number TEXT NOT NULL UNIQUE,
  revision TEXT NOT NULL DEFAULT 'A',
  title TEXT NOT NULL DEFAULT '',
  trade TEXT NOT NULL DEFAULT '',
  asset TEXT NOT NULL DEFAULT '',
  location TEXT NOT NULL DEFAULT '',
  additional_info TEXT NOT NULL DEFAULT '',
  created_by_name TEXT NOT NULL DEFAULT '',
  created_by_position TEXT NOT NULL DEFAULT '',
  created_date TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE jobcard_flag (
  jobcard_id INTEGER NOT NULL REFERENCES jobcard(id) ON DELETE CASCADE,
  flag TEXT NOT NULL,
  PRIMARY KEY (jobcard_id, flag)
);
CREATE TABLE drawing (
  id INTEGER PRIMARY KEY,
  jobcard_id INTEGER NOT NULL REFERENCES jobcard(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  number TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE task (
  id INTEGER PRIMARY KEY,
  jobcard_id INTEGER NOT NULL REFERENCES jobcard(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  qty REAL,
  norm_hours REAL,
  basis TEXT NOT NULL DEFAULT '',          -- 'library' or 'manual' (manual norms say why here)
  norm_key TEXT NOT NULL DEFAULT '',
  norm_uom TEXT NOT NULL DEFAULT '',
  norm_desc TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'manual',   -- library | manual
  factor REAL NOT NULL DEFAULT 1,
  factor_reason TEXT NOT NULL DEFAULT '',
  factor_set_by TEXT NOT NULL DEFAULT '',
  factor_set_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE snapshot (
  id INTEGER PRIMARY KEY,
  workpack_id INTEGER NOT NULL REFERENCES workpack(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE snapshot_line (
  snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
  trade TEXT NOT NULL,
  library_hours REAL NOT NULL DEFAULT 0,
  manual_hours REAL NOT NULL DEFAULT 0
);
CREATE INDEX ix_jobcard_wp ON jobcard(workpack_id);
CREATE INDEX ix_task_jc ON task(jobcard_id);