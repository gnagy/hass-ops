from pathlib import Path

import pytest

from hass_ops import project

TOML = """
[paths]
config = "cfg"

[check]
skip_dirs = ["www", "zha_quirks"]

[instances.prod]
url = "https://prod.example/"
ssh = "prod-host"
default = true

[instances.test]
url = "https://test.example"
ssh = "test-host"
"""


@pytest.fixture
def proj_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / project.FILENAME).write_text(TOML)
    (tmp_path / "sub" / "deeper").mkdir(parents=True)
    monkeypatch.delenv("HA_INSTANCE", raising=False)
    monkeypatch.delenv("HASS_OPS_PROJECT", raising=False)
    return tmp_path


def test_find_walks_up(proj_dir: Path) -> None:
    assert project.find(proj_dir / "sub" / "deeper") == proj_dir / project.FILENAME


def test_find_fails_outside_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HASS_OPS_PROJECT", raising=False)
    with pytest.raises(project.ProjectError):
        project.find(tmp_path)


def test_paths_are_relative_to_the_file_with_defaults(proj_dir: Path) -> None:
    p = project.load(proj_dir / project.FILENAME)
    assert p.config == (proj_dir / "cfg").resolve()
    assert p.desired == (proj_dir / "desired").resolve()
    assert p.exports == (proj_dir / "exports").resolve()
    assert p.skip_dirs == {"www", "zha_quirks"}
    assert p.instances["prod"].url == "https://prod.example"


def test_instance_precedence(proj_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = project.load(proj_dir / project.FILENAME)
    assert p.instance().name == "prod"  # the file's default
    monkeypatch.setenv("HA_INSTANCE", "test")
    assert p.instance().name == "test"  # environment beats the default
    assert p.instance("prod").name == "prod"  # the flag beats the environment


def test_unknown_instance_is_refused(proj_dir: Path) -> None:
    p = project.load(proj_dir / project.FILENAME)
    with pytest.raises(project.ProjectError, match="unknown instance 'staging'"):
        p.instance("staging")


def test_activate_publishes_the_choice(proj_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_TEST_URL", "https://stale.example")
    _, target = project.activate(proj_dir, "test")
    import os

    assert target.name == "test"
    assert os.environ["HA_INSTANCE"] == "test"
    assert os.environ["HA_TEST_URL"] == "https://test.example"  # the file wins
    assert os.environ["HA_TEST_SSH"] == "test-host"
