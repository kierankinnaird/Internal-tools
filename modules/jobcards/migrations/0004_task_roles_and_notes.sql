ALTER TABLE task ADD COLUMN role TEXT NOT NULL DEFAULT '';   -- 'first' or 'last' for a standard task, '' for any other
ALTER TABLE task ADD COLUMN note TEXT NOT NULL DEFAULT '';   -- the task's note, as cleaned HTML (see richtext.py)
