"""Launcher regressions: setup completeness, saved settings, and occupied ports."""
import socket
import subprocess
from pathlib import Path
import pytest
import launch


def project(tmp_path):
    (tmp_path / "requirements.txt").write_text("example-package==1\n")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\n")
    python = launch.environment_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.touch()
    return python


def test_cached_environment_skips_install_and_preserves_existing_key(tmp_path, monkeypatch):
    python = project(tmp_path)
    stamp = tmp_path / ".venv" / ".paper-radio-requirements"
    stamp.write_text(launch.dependency_signature(tmp_path))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=existing-test-placeholder\n")
    monkeypatch.setattr(launch, "dependencies_ready", lambda _: True)
    def forbidden(*args, **kwargs):
        pytest.fail("An unchanged, healthy environment must not reinstall dependencies.")
    monkeypatch.setattr(launch.subprocess, "run", forbidden)
    assert launch.prepare(tmp_path) == python
    assert (tmp_path / ".env").read_text() == "OPENAI_API_KEY=existing-test-placeholder\n"


def test_first_launch_installs_the_complete_requirements_file(tmp_path, monkeypatch):
    python = project(tmp_path)
    calls = []
    monkeypatch.setattr(launch.subprocess, "run", lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(launch, "dependencies_ready", lambda _: True)
    assert launch.prepare(tmp_path) == python
    assert calls == [[str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(tmp_path / "requirements.txt")]]
    assert (tmp_path / ".env").read_text() == "OPENAI_API_KEY=\n"
    assert (tmp_path / ".venv" / ".paper-radio-requirements").read_text().strip() == launch.dependency_signature(tmp_path)


def test_missing_packages_trigger_repair_even_with_matching_stamp(tmp_path, monkeypatch):
    project(tmp_path)
    (tmp_path / ".venv" / ".paper-radio-requirements").write_text(launch.dependency_signature(tmp_path))
    checks = iter([False, True])
    calls = []
    monkeypatch.setattr(launch, "dependencies_ready", lambda _: next(checks))
    monkeypatch.setattr(launch.subprocess, "run", lambda command, **kwargs: calls.append(command))
    launch.prepare(tmp_path)
    assert len(calls) == 1 and "-r" in calls[0]


def test_failed_install_does_not_mark_environment_as_ready(tmp_path, monkeypatch):
    project(tmp_path)
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(launch.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        launch.prepare(tmp_path)
    assert not (tmp_path / ".venv" / ".paper-radio-requirements").exists()


def test_a_new_virtual_environment_is_created_when_needed(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("example-package==1\n")
    created = []
    class Builder:
        def __init__(self, **kwargs):
            assert kwargs["with_pip"] is True
        def create(self, target):
            created.append(target)
            python = launch.environment_python(tmp_path)
            python.parent.mkdir(parents=True)
            python.touch()
    monkeypatch.setattr(launch.venv, "EnvBuilder", Builder)
    monkeypatch.setattr(launch.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(launch, "dependencies_ready", lambda _: True)
    launch.prepare(tmp_path)
    assert created == [tmp_path / ".venv"]


def test_occupied_port_is_skipped_without_stopping_the_other_app():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        if port >= 65525:
            pytest.skip("The OS allocated the last port range.")
        assert port < launch.available_port(port) <= port + 10
