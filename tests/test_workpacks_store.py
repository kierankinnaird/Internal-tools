import hashlib
from pathlib import Path

from modules.workpacks.store import ENV_VAR, MANIFEST, TemplateStore, default_folder


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pack(folder: Path, files: dict, manifest: bool = True, extra_rows=()):
    """A pretend templates pack: the files, and a manifest listing them."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    if manifest:
        lines = ["file,sha256,labelled header boxes,apache original sha256"]
        lines += [f"{n},{sha(d)},no," for n, d in files.items()]
        lines += list(extra_rows)
        (folder / MANIFEST).write_text("\ufeff" + "\n".join(lines) + "\n", encoding="utf-8")


def test_a_folder_that_is_not_there_is_not_present(tmp_path):
    s = TemplateStore(tmp_path / "nope").status()
    assert not s.present and not s.ok and s.docx_count == 0


def test_an_empty_folder_is_not_present(tmp_path):
    (tmp_path / "t").mkdir()
    assert not TemplateStore(tmp_path / "t").status().present


def test_a_complete_pack_is_ok(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one", "SL1.docx": b"two", "Index.xlsx": b"three"})
    s = TemplateStore(tmp_path / "t").status()
    assert s.ok and s.present and s.docx_count == 2 and s.manifest_found
    assert (s.differs, s.missing, s.unlisted) == ([], [], [])


def test_no_manifest_means_not_ok_but_templates_are_still_counted(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one"}, manifest=False)
    s = TemplateStore(tmp_path / "t").status()
    assert s.present and s.docx_count == 1 and not s.manifest_found and not s.ok


def test_a_changed_file_is_reported_as_differing(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one", "SL1.docx": b"two"})
    (tmp_path / "t" / "SL1.docx").write_bytes(b"edited")
    s = TemplateStore(tmp_path / "t").status()
    assert s.differs == ["SL1.docx"] and not s.ok


def test_a_missing_file_is_reported(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one", "SL1.docx": b"two"})
    (tmp_path / "t" / "SL1.docx").unlink()
    s = TemplateStore(tmp_path / "t").status()
    assert s.missing == ["SL1.docx"] and not s.ok


def test_an_extra_file_is_listed_but_does_not_fail_the_check(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one"})
    (tmp_path / "t" / "NEW1.docx").write_bytes(b"newer revision")
    s = TemplateStore(tmp_path / "t").status()
    assert s.unlisted == ["NEW1.docx"] and s.ok


def test_apache_original_is_accepted_where_the_manifest_says_so(tmp_path):
    pack(tmp_path / "t", {}, extra_rows=[f"SH1.docx,{sha(b'labelled')},yes,{sha(b'original')}"])
    (tmp_path / "t" / "SH1.docx").write_bytes(b"original")
    assert TemplateStore(tmp_path / "t").status().differs == []
    (tmp_path / "t" / "SH1.docx").write_bytes(b"labelled")
    assert TemplateStore(tmp_path / "t").status().differs == []
    (tmp_path / "t" / "SH1.docx").write_bytes(b"something else")
    assert TemplateStore(tmp_path / "t").status().differs == ["SH1.docx"]


def test_the_same_store_notices_a_file_changing_later(tmp_path):
    pack(tmp_path / "t", {"AS1.docx": b"one"})
    store = TemplateStore(tmp_path / "t")
    assert store.status().ok
    (tmp_path / "t" / "AS1.docx").write_bytes(b"changed!")
    assert store.status().differs == ["AS1.docx"]


def test_default_folder_is_inside_the_data_folder_unless_overridden(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert default_folder(tmp_path) == tmp_path / "workpacks" / "templates"
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "elsewhere"))
    assert default_folder(tmp_path) == tmp_path / "elsewhere"
    monkeypatch.setenv(ENV_VAR, "   ")
    assert default_folder(tmp_path) == tmp_path / "workpacks" / "templates"