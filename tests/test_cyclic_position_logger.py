"""CyclicPositionLogger must never write inside the installed package."""

from pathlib import Path

import mhsim
from mhsim.cyclic_position_logger import CyclicPositionLogger


def test_relative_log_dir_resolves_against_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = CyclicPositionLogger(log_dir="traces")
    assert logger.log_dir == tmp_path / "traces"
    assert logger.log_dir.is_dir()


def test_default_log_dir_is_outside_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = CyclicPositionLogger()
    package_root = Path(mhsim.__file__).resolve().parents[1]
    assert not logger.log_dir.resolve().is_relative_to(package_root)


def test_absolute_log_dir_is_kept(tmp_path):
    target = tmp_path / "abs"
    assert CyclicPositionLogger(log_dir=target).log_dir == target
