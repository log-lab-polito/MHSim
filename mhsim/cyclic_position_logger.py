"""Cyclic transporter position logging in the AnyLogic trace format."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generator, Iterable, Optional, TextIO

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps simpy off the import path
    import simpy
    from types import TracebackType



class CyclicPositionLogger:
    """Write AnyLogic-style cyclic transporter position rows."""

    def __init__(
        self,
        log_dir: str = "logs",
        filename_prefix: str = "simpy_model1",
        position_scale: float = 1.0,
    ) -> None:
        """Prepare a timestamped log file without opening it.

        The file name is fixed at construction, so two loggers created in the
        same second share a name.

        Args:
            log_dir: Directory for the log. Relative paths resolve against the
                current working directory; pass an absolute path to pin the
                location regardless of where the run is launched. Created if
                missing.
            filename_prefix: Leading part of the file name, followed by a
                `_YYYYmmdd_HHMMSS.txt` timestamp.
            position_scale: Multiplier applied to `x` and `y` on write. Use it
                when the model works in different units from the AnyLogic
                export being compared against.
        """
        log_path = Path(log_dir)
        self.log_dir = log_path if log_path.is_absolute() else Path.cwd() / log_path
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.position_scale = position_scale

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"{filename_prefix}_{timestamp}.txt"

        self._file: Optional[TextIO] = None
        self._process = None

    def open(self) -> None:
        """Open the log file for writing."""
        if self._file is None:
            self._file = open(self.log_file, "w", encoding="utf-8")

    def close(self) -> None:
        """Close the log file."""
        if self._file is not None:
            self._file.close()
            self._file = None
        self._process = None

    def start(
        self,
        env: "simpy.Environment",
        forklifts: Iterable[object],
        interval_s: float = 0.1,
    ) -> "simpy.Process":
        """Start cyclic position logging for the given forklift fleet."""
        if self._process is not None:
            return self._process

        forklift_list = list(forklifts)
        self._process = env.process(self._run(env, forklift_list, interval_s))
        return self._process

    def _run(
        self,
        env: "simpy.Environment",
        forklifts: list[object],
        interval_s: float,
    ) -> Generator:
        while True:
            self.log_positions(env.now, forklifts)
            yield env.timeout(interval_s)

    def log_positions(self, time: float, forklifts: Iterable[object]) -> None:
        """Write one AnyLogic-style position row for all forklifts."""
        if self._file is None:
            return

        message = f"t={time:.2f}"
        for forklift in forklifts:
            position = getattr(forklift, "position")
            x = position.x * self.position_scale
            y = position.y * self.position_scale
            message += f", x={x:.2f}, y={y:.2f}"

        self._file.write(message + "\n")
        self._file.flush()

    def log_event(self, *args, **kwargs) -> None:
        """Compatibility shim for blocks that still accept a logger."""
        return None

    def __enter__(self) -> "CyclicPositionLogger":
        """Context manager entry."""
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: "TracebackType | None",
    ) -> None:
        """Context manager exit."""
        self.close()
