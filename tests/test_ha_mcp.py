from pathlib import Path

import pytest

from hass_ops import cli, ha_mcp, project

TOML = """
[instances.prod]
url = "https://prod.example"
token_command = "printf prod-tok"
default = true

[instances.test]
url = "https://test.example"
token_command = "printf test-tok"

[instances.test.ha_mcp]
read_only = false
env = { LOG_LEVEL = "DEBUG" }

[ha_mcp]
package = "ha-mcp==8.5.0"

[ha_mcp.env]
ENABLE_TOOL_SEARCH = true
LOG_LEVEL = "WARNING"
"""


@pytest.fixture
def proj_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / project.FILENAME).write_text(TOML)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for var in ("HA_INSTANCE", "HASS_OPS_PROJECT", "HA_PROD_TOKEN", "HA_TEST_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _build(proj_dir: Path, instance: str) -> tuple[list[str], dict[str, str]]:
    proj, target = project.activate(proj_dir, instance)
    return ha_mcp.build(proj, target)


def test_read_only_unless_the_file_says_otherwise(proj_dir: Path) -> None:
    command, env = _build(proj_dir, "prod")
    assert command == ["uvx", "ha-mcp==8.5.0"]
    assert env["READ_ONLY_MODE"] == "true"
    assert env["HOMEASSISTANT_URL"] == "https://prod.example"
    assert env["HOMEASSISTANT_TOKEN"] == "prod-tok"
    assert env["HA_MCP_DISABLE_SETTINGS_UI"] == "1"
    assert env["HA_MCP_CONFIG_DIR"] == str(proj_dir / "home" / ".ha-mcp" / "prod")
    assert env["ENABLE_TOOL_SEARCH"] == "true"  # a TOML boolean, written the way ha-mcp reads it
    assert env["LOG_LEVEL"] == "WARNING"


def test_instance_settings_override_shared_ones(proj_dir: Path) -> None:
    _, env = _build(proj_dir, "test")
    assert env["READ_ONLY_MODE"] == "false"
    assert env["LOG_LEVEL"] == "DEBUG"
    assert env["HOMEASSISTANT_TOKEN"] == "test-tok"
    assert env["HA_MCP_CONFIG_DIR"].endswith("/.ha-mcp/test")


@pytest.mark.parametrize("key", sorted(project.RESERVED_MCP_ENV))
def test_env_tables_may_not_set_what_hass_ops_owns(proj_dir: Path, key: str) -> None:
    (proj_dir / project.FILENAME).write_text(TOML + f'{key} = "x"\n')
    with pytest.raises(project.ProjectError, match=f"may not set {key}"):
        project.load(proj_dir / project.FILENAME)


def test_read_only_must_be_a_boolean(proj_dir: Path) -> None:
    (proj_dir / project.FILENAME).write_text(TOML.replace("read_only = false", 'read_only = "no"'))
    with pytest.raises(project.ProjectError, match="read_only must be true or false"):
        project.load(proj_dir / project.FILENAME)


def test_package_is_required(proj_dir: Path) -> None:
    (proj_dir / project.FILENAME).write_text(TOML.replace('package = "ha-mcp==8.5.0"', ""))
    with pytest.raises(project.ProjectError, match=r"\[ha_mcp\] needs package"):
        project.load(proj_dir / project.FILENAME)


def test_without_an_ha_mcp_table_the_command_refuses(proj_dir: Path) -> None:
    (proj_dir / project.FILENAME).write_text(TOML.split("[ha_mcp]")[0])
    assert cli.main(["-C", str(proj_dir), "ha-mcp", "--print"]) == 2


def test_print_hides_the_token(proj_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["-C", str(proj_dir), "-i", "test", "ha-mcp", "--print"]) == 0
    out = capsys.readouterr().out
    assert "HOMEASSISTANT_TOKEN=<hidden>" in out
    assert "test-tok" not in out
    assert "READ_ONLY_MODE=false" in out
    assert out.rstrip().endswith("uvx ha-mcp==8.5.0")
