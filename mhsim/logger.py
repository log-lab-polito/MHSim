from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO


class SimulationLogger:
    """Logger for SimPy model events to match AnyLogic console output format."""

    def __init__(self, log_dir: str = "logs", filename_prefix: str = "simpy_model1"):
        """Initialize logger with timestamped log file.

        Args:
            log_dir: Directory to store log files
            filename_prefix: Prefix for log filename
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"{filename_prefix}_{timestamp}.txt"

        self._file: Optional[TextIO] = None

    def open(self):
        """Open the log file for writing."""
        if self._file is None:
            self._file = open(self.log_file, 'w', encoding='utf-8')

    def close(self):
        """Close the log file."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def log_event(self, block_name: str, pallet_info: str, time: Optional[float] = None):
        """Log a pallet event.

        Args:
            block_name: Name of the block (e.g., "service1 block", "store block", "delay block")
            pallet_info: Information about the pallet (e.g., "Pallet 1")
            time: Simulation time (if None, won't be logged)
        """
        if self._file is None:
            return

        if time is not None:
            # Format time as integer if it's a whole number, otherwise with decimals
            if isinstance(time, (int, float)) and time == int(time):
                time_str = f"{int(time)}.0"
            else:
                time_str = str(time)
            message = f"{pallet_info} entering {block_name} at {time_str}"
        else:
            message = f"{block_name} {pallet_info}"

        self._file.write(message + "\n")
        self._file.flush()

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
