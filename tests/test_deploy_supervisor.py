"""Device-local Supervisor installation without modifying tracked templates."""

import configparser
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy"


def make_project(path):
    (path / ".venv" / "bin").mkdir(parents=True)
    (path / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (path / "main.py").write_text("import os; print(os.getcwd())\n")
    return path


@pytest.mark.parametrize("explicit_path", [False, True])
def test_install_from_another_directory(tmp_path, explicit_path):
    project = make_project(tmp_path / "cash register 100%")
    shutil.copytree(DEPLOY_DIR, project / "deploy")
    template = (project / "deploy" / "flesh.conf").read_bytes()
    output = tmp_path / "etc" / "supervisor" / "conf.d" / "flesh.conf"
    script = DEPLOY_DIR if explicit_path else project / "deploy"
    command = [sys.executable, str(script / "install_supervisor.py"), "--output", str(output)]
    if explicit_path:
        command.extend(["--project-dir", str(project)])
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)

    config = configparser.ConfigParser()
    config.read(output)
    program = config["program:flesh"]
    assert program["directory"] == str(project)
    assert program.getboolean("autostart")
    assert program.getboolean("autorestart")
    assert program.getint("numprocs") == 1
    # Exercise the generated command, including quoting and percent interpolation.
    result = subprocess.run(
        shlex.split(program["command"]), cwd=program["directory"],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == str(project)
    assert (project / "deploy" / "flesh.conf").read_bytes() == template


def test_missing_venv_preserves_installed_config(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").touch()
    output = tmp_path / "flesh.conf"
    output.write_text("existing configuration\n")
    result = subprocess.run(
        [sys.executable, str(DEPLOY_DIR / "install_supervisor.py"),
         "--project-dir", str(project), "--output", str(output)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Create .venv first" in result.stderr
    assert output.read_text() == "existing configuration\n"
