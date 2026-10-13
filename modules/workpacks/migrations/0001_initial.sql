-- Workpacks: the project details, certificates and table rows that used to live in the input workbook.
-- Plain SQL on purpose (no SQLite-only features) so the same schema can move to a shared database later.
-- Column names follow the input sheet so an imported workbook maps one to one.

CREATE TABLE workpack (
    id                INTEGER PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT '',   -- project title, shown in every form header
    project_no        TEXT NOT NULL DEFAULT '',   -- FCP number
    workpack_no       TEXT NOT NULL DEFAULT '',   -- Apache document / CCHP number
    sh1_no            TEXT NOT NULL DEFAULT '',
    mc1_no            TEXT NOT NULL DEFAULT '',
    site              TEXT NOT NULL DEFAULT '',
    location          TEXT NOT NULL DEFAULT '',   -- defaults for certificates that leave these blank
    system            TEXT NOT NULL DEFAULT '',
    subsystem         TEXT NOT NULL DEFAULT '',
    handover_title    TEXT NOT NULL DEFAULT '',   -- SH1 / MC1; blank means the project title
    handover_includes TEXT NOT NULL DEFAULT '',
    handover_excludes TEXT NOT NULL DEFAULT '',
    ee12_description  TEXT NOT NULL DEFAULT '',   -- standard description of tests
    nmc_cchp_no       TEXT NOT NULL DEFAULT '',   -- workpack master (DM) only
    revision          TEXT NOT NULL DEFAULT '',   -- workpack master (DM) only
    cover_title       TEXT NOT NULL DEFAULT '',   -- workpack master (DM) only
    jre               TEXT NOT NULL DEFAULT '',   -- CCHP checklist (C1) only
    cchp_title        TEXT NOT NULL DEFAULT '',   -- CCHP checklist (C1) only
    created_at        TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    updated_by        TEXT NOT NULL
);

CREATE TABLE certificate (
    id               INTEGER PRIMARY KEY,
    workpack_id      INTEGER NOT NULL REFERENCES workpack(id) ON DELETE CASCADE,
    position         INTEGER NOT NULL DEFAULT 0,  -- order on the page
    cert_id          TEXT NOT NULL,               -- short unique name, e.g. AS1-PL33000
    form             TEXT NOT NULL,               -- C1, DM, AS1, EE12, SC1, SL1, MP1, JI1, SH1, MC1, PL1 A, PL1 B, ...
    filename         TEXT NOT NULL DEFAULT '',    -- output file name without .docx; blank means '<form> <id>'
    equipment        TEXT NOT NULL DEFAULT '',
    location         TEXT NOT NULL DEFAULT '',
    area             TEXT NOT NULL DEFAULT '',
    system           TEXT NOT NULL DEFAULT '',
    subsystem        TEXT NOT NULL DEFAULT '',
    drawing          TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    scope            TEXT NOT NULL DEFAULT '',
    procedure        TEXT NOT NULL DEFAULT '',
    ee12_description TEXT NOT NULL DEFAULT '',    -- overrides the workpack's standard description
    punch_no         TEXT NOT NULL DEFAULT '',
    discipline       TEXT NOT NULL DEFAULT '',
    folder           TEXT NOT NULL DEFAULT '',
    sl1a             TEXT NOT NULL DEFAULT '',
    hdr_title        TEXT NOT NULL DEFAULT '',    -- this certificate's header only
    hdr_site         TEXT NOT NULL DEFAULT '',
    hdr_mc1_no       TEXT NOT NULL DEFAULT '',
    UNIQUE (workpack_id, cert_id)
);
CREATE INDEX certificate_workpack ON certificate (workpack_id, position);

-- SL1 / MP1 line table
CREATE TABLE line (
    id             INTEGER PRIMARY KEY,
    certificate_id INTEGER NOT NULL REFERENCES certificate(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL DEFAULT 0,
    pid            TEXT NOT NULL DEFAULT '',      -- SL1: P&ID no. MP1: ISO no.
    line_no        TEXT NOT NULL DEFAULT '',
    from_equipment TEXT NOT NULL DEFAULT '',
    to_equipment   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX line_certificate ON line (certificate_id, position);

-- JI1 joint table
CREATE TABLE joint (
    id             INTEGER PRIMARY KEY,
    certificate_id INTEGER NOT NULL REFERENCES certificate(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL DEFAULT 0,
    joint_no       TEXT NOT NULL DEFAULT '',
    drawing        TEXT NOT NULL DEFAULT '',
    size           TEXT NOT NULL DEFAULT '',      -- flange size (NB)
    rating         TEXT NOT NULL DEFAULT '',
    joint_type     TEXT NOT NULL DEFAULT '',
    torque         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX joint_certificate ON joint (certificate_id, position);

-- EE12 tag table
CREATE TABLE tag (
    id             INTEGER PRIMARY KEY,
    certificate_id INTEGER NOT NULL REFERENCES certificate(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL DEFAULT 0,
    tag            TEXT NOT NULL DEFAULT '',
    drawing        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX tag_certificate ON tag (certificate_id, position);
