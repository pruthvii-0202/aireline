import pytest

from skypoints.config import SnowflakeSettings, parse_env_file

FULL = {"SNOWFLAKE_ACCOUNT": "acct", "SNOWFLAKE_USER": "me", "SNOWFLAKE_PASSWORD": "s3cret"}


def test_parse_env_file_skips_comments_and_strips_quotes():
    text = "# comment\n\nSNOWFLAKE_USER = 'me'\nSNOWFLAKE_ROLE=\"SYSADMIN\"\nnot a pair\n"
    assert parse_env_file(text) == {"SNOWFLAKE_USER": "me", "SNOWFLAKE_ROLE": "SYSADMIN"}


def test_defaults_applied():
    s = SnowflakeSettings.from_env(FULL, env_file=None)
    assert (s.role, s.warehouse, s.database) == ("SYSADMIN", "COMPUTE_WH", "SKYPOINTS_DEV")


def test_missing_required_lists_every_missing_key():
    with pytest.raises(RuntimeError, match="SNOWFLAKE_USER, SNOWFLAKE_PASSWORD"):
        SnowflakeSettings.from_env({"SNOWFLAKE_ACCOUNT": "acct"}, env_file=None)


def test_environment_overrides_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SNOWFLAKE_USER=from_file\nSNOWFLAKE_WAREHOUSE=FILE_WH\n")
    s = SnowflakeSettings.from_env(FULL, env_file=env_file)
    assert s.user == "me"
    assert s.warehouse == "FILE_WH"


def test_repr_hides_password():
    assert "s3cret" not in repr(SnowflakeSettings.from_env(FULL, env_file=None))
