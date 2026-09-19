import sys
from pathlib import Path

import pytest

from hass_ops import cli, project


@pytest.fixture
def proj_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / project.FILENAME).write_text(
        '[instances.test]\nurl = "https://test.example"\nssh = "test-host"\n'
        "token_command = \"printf tok\"\ndefault = true\n"
    )
    for var in ("HA_INSTANCE", "HASS_OPS_PROJECT", "HA_TEST_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_exec_publishes_the_instance(proj_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "env.txt"
    code = cli.main([
        "-C", str(proj_dir), "exec", "--", sys.executable, "-c",
        f"import os; open({str(out)!r}, 'w').write(' '.join(os.environ[k] for k in "
        "('HA_INSTANCE', 'HA_TEST_URL', 'HA_TEST_SSH', 'HA_TEST_TOKEN')))",
    ])
    assert code == 0
    assert out.read_text() == "test https://test.example test-host tok"


def test_exec_passes_the_exit_code(proj_dir: Path) -> None:
    assert cli.main(["-C", str(proj_dir), "exec", "--", sys.executable, "-c", "raise SystemExit(7)"]) == 7


def test_exec_without_a_command(proj_dir: Path) -> None:
    assert cli.main(["-C", str(proj_dir), "exec"]) == 64
