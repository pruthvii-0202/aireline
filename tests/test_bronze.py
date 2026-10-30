from datetime import date
from pathlib import Path

import pytest

from skypoints.bronze.loader import (
    MEMBER_PROFILE,
    REDEMPTIONS,
    classify,
    discover,
    expected_rows,
    summarise_copy,
)
from skypoints.sql_runner import ddl_scripts, render


def test_classify_member_and_redemption_files():
    member = classify(Path("MEMBER_PROFILE_20240115_06000000.txt"))
    redemption = classify(Path("REDEMPTIONS_20240116.json"))
    assert (member.feed, member.batch_date) == (MEMBER_PROFILE, date(2024, 1, 15))
    assert (redemption.feed, redemption.batch_date) == (REDEMPTIONS, date(2024, 1, 16))


@pytest.mark.parametrize(
    "name",
    ["MANIFEST_20240115.json", "MEMBER_PROFILE_2024011_06000000.txt", "REDEMPTIONS_20240115.txt"],
)
def test_classify_ignores_other_files(name):
    assert classify(Path(name)) is None


def test_discover_orders_by_date_then_members_first(tmp_path):
    for name in (
        "REDEMPTIONS_20240116.json",
        "MEMBER_PROFILE_20240116_06000000.txt",
        "REDEMPTIONS_20240115.json",
        "MEMBER_PROFILE_20240115_06000000.txt",
        "MANIFEST_20240115.json",
    ):
        (tmp_path / name).write_text("x\n")
    assert [lf.path.name for lf in discover(tmp_path)] == [
        "MEMBER_PROFILE_20240115_06000000.txt",
        "REDEMPTIONS_20240115.json",
        "MEMBER_PROFILE_20240116_06000000.txt",
        "REDEMPTIONS_20240116.json",
    ]


def test_expected_rows_counts_non_empty_lines(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("|H|a\n|D|1\n\n|D|2\n")
    assert expected_rows(f) == 3


def test_summarise_copy_sums_files_and_flags_errors():
    rows = [
        {"rows_parsed": 10, "rows_loaded": 9, "errors_seen": 1, "first_error": "bad"},
        {"rows_parsed": 5, "rows_loaded": 5, "errors_seen": 0, "first_error": None},
    ]
    assert summarise_copy(rows) == {
        "status": "LOADED_WITH_ERRORS",
        "rows_parsed": 15,
        "rows_loaded": 14,
        "errors_seen": 1,
        "first_error": "bad",
    }


def test_summarise_copy_already_in_load_history():
    rows = [{"status": "Copy executed with 0 files processed."}]
    assert summarise_copy(rows)["status"] == "SKIPPED_BY_COPY"


def test_render_fills_placeholders():
    assert render("USE {{ database }}.{{schema}}", {"database": "DB", "schema": "S"}) == "USE DB.S"


def test_render_unknown_placeholder_fails():
    with pytest.raises(KeyError):
        render("USE {{ nope }}", {})


def test_ddl_scripts_sorted_numerically(tmp_path):
    for name in ("V010__c.sql", "V002__b.sql", "V001__a.sql", "notes.md"):
        (tmp_path / name).write_text("")
    assert [p.name for p in ddl_scripts(tmp_path)] == ["V001__a.sql", "V002__b.sql", "V010__c.sql"]


def test_repo_ddl_scripts_render_with_database_only():
    scripts = ddl_scripts(Path("sql/ddl"))
    assert scripts
    for script in scripts:
        assert "{{" not in render(script.read_text(), {"database": "SKYPOINTS_DEV"})
