from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TextIO


def _format_hms(seconds: float) -> str:
    total_seconds = int(max(0.0, seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


ANSI = {
    "reset": "\x1b[0m",
    "grey": "\x1b[90m",
    "green": "\x1b[92m",
    "yellow": "\x1b[93m",
    "blue": "\x1b[94m",
    "magenta": "\x1b[95m",
    "cyan": "\x1b[96m",
    "red": "\x1b[91m",
}


@dataclass
class TraceConfig:
    enabled: bool = True
    use_color: bool = True
    prefix_time: bool = True  # wall-clock time prefix
    flush: bool = True
    log_path: Optional[str] = None
    log_append: bool = False
    console_level: str = "full"  # full, summary, silent


class Tracer:
    def __init__(self, cfg: Optional[TraceConfig] = None) -> None:
        self.cfg = cfg or TraceConfig()
        self._log_file: Optional[TextIO] = None
        self._csv_writer = None
        if self.cfg.log_path:
            log_path = Path(self.cfg.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if self.cfg.log_append else "w"
            self._log_file = open(self.cfg.log_path, mode,
                                  encoding="utf-8", newline="")
            self._init_csv()

    def _init_csv(self) -> None:
        if self._log_file:
            self._csv_writer = csv.writer(self._log_file)
            self._csv_writer.writerow(
                ["sim_time", "wall_time", "channel", "message"])
            if self.cfg.flush:
                self._log_file.flush()

    def _format_console(self, out: str, color: Optional[str]) -> str:
        if self.cfg.use_color and color:
            return f"{ANSI.get(color, '')}{out}{ANSI['reset']}"
        return out

    def _should_print_console(self, channel: str) -> bool:
        level = (self.cfg.console_level or "full").lower()
        if level == "silent":
            return False
        if level == "summary" and channel == "detail":
            return False
        return True

    def _write_csv_row(
        self,
        message: str,
        sim_time: Optional[float],
        wall_time: str,
        channel: str,
    ) -> None:
        if self._csv_writer:
            sim_val = f"{sim_time:.2f}" if isinstance(
                sim_time, (int, float)) else ""
            self._csv_writer.writerow([sim_val, wall_time, channel, message])

    def _emit(
        self,
        s: str,
        color: Optional[str] = None,
        end: str = "\n",
        *,
        sim_time: Optional[float] = None,
        channel: str = "detail",
    ) -> None:
        if not self.cfg.enabled:
            return
        channel = channel or "detail"
        wall_stamp = time.strftime("%H:%M:%S")
        disp = s
        if sim_time is not None:
            disp = f"{sim_time:10.2f}s ({_format_hms(sim_time)})  {disp}"
        out = disp
        if self.cfg.prefix_time:
            out = f"[{wall_stamp}] " + out

        if self._should_print_console(channel):
            console_out = self._format_console(out, color)
            print(console_out, end=end, file=sys.stdout)
            if self.cfg.flush:
                sys.stdout.flush()

        if self._log_file:
            self._write_csv_row(s, sim_time, wall_stamp, channel)
            if self.cfg.flush:
                self._log_file.flush()

    def trace(
        self,
        s: str,
        *,
        color: Optional[str] = None,
        sim_time: Optional[float] = None,
        channel: str = "detail",
    ) -> None:
        self._emit(s, color=color, end="", sim_time=sim_time, channel=channel)

    def traceln(
        self,
        s: str,
        *,
        color: Optional[str] = None,
        sim_time: Optional[float] = None,
        channel: str = "detail",
    ) -> None:
        self._emit(s, color=color, end="\n",
                   sim_time=sim_time, channel=channel)

    def close(self) -> None:
        if self._log_file:
            self._log_file.close()
            self._log_file = None


# convenience singletons
_default_tracer = Tracer()


def trace(
    o: object,
    *,
    color: Optional[str] = None,
    sim_time: Optional[float] = None,
    channel: str = "detail",
) -> None:
    _default_tracer.trace(str(o), color=color,
                          sim_time=sim_time, channel=channel)


def traceln(
    o: object,
    *,
    color: Optional[str] = None,
    sim_time: Optional[float] = None,
    channel: str = "detail",
) -> None:
    _default_tracer.traceln(str(o), color=color,
                            sim_time=sim_time, channel=channel)


def get_tracer() -> Tracer:
    return _default_tracer


def set_tracer(tracer: Tracer) -> None:
    global _default_tracer
    old_tracer = _default_tracer
    _default_tracer = tracer
    if old_tracer is not tracer:
        old_tracer.close()


__all__ = [
    "TraceConfig",
    "Tracer",
    "trace",
    "traceln",
    "get_tracer",
    "set_tracer",
]
