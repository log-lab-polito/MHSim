"""Write shorter CSV copies with every numeric cell rounded to 2 decimals.

The output files are written next to this script with "_shorter" appended
before the ".csv" extension. Numeric output uses a dot decimal separator and no
thousands separators so Apple Numbers can import the values as numbers.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


CSV_FILES = [
    # "model_1_benchmark_comparison.csv",
    # "model_1_forklift_benchmarks.csv",
    # "model_1_parameter_variation_range_runs.csv",
    # "model_1_parameter_variation_range_summary.csv",
    # "model_2_benchmark_comparison.csv",
    # "model_2_forklift_benchmarks.csv",
    # "model_5_benchmark_comparison.csv",
    # "model_5_benchmark_comparison_sample.csv",
    # "model_5_forklift_benchmarks.csv",
    # "model_5_forklift_benchmarks_smoke.csv",
    # "model_5_forklift_benchmarks_updated.csv",
    # "model_5_parameter_variation_range_runs.csv",
    # "model_5_parameter_variation_range_summary.csv",
    "model_2_parameter_variation_range_runs.csv",
    "model_2_parameter_variation_range_summary.csv",
    # "run_jobshop_salabim.csv",
    # "run_jobshop_simpy.csv",
]

TWO_DECIMALS = Decimal("0.01")


def shorten_number(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return value

    try:
        decimal_value = Decimal(stripped)
    except InvalidOperation:
        return value

    if not decimal_value.is_finite():
        return value

    rounded = decimal_value.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def output_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}_shorter{source_path.suffix}")


def convert_file(source_path: Path) -> Path:
    destination_path = output_path(source_path)

    with source_path.open("r", newline="", encoding="utf-8") as source_file:
        sample = source_file.read(4096)
        source_file.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample) if sample else csv.excel
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(source_file, dialect)

        with destination_path.open("w", newline="", encoding="utf-8") as destination_file:
            writer = csv.writer(destination_file, lineterminator="\n")
            for row in reader:
                writer.writerow([shorten_number(cell) for cell in row])

    return destination_path


def main() -> None:
    script_dir = Path(__file__).resolve().parent

    for file_name in CSV_FILES:
        source_path = script_dir / file_name
        if not source_path.exists():
            print(f"Missing: {source_path}")
            continue

        destination_path = convert_file(source_path)
        print(f"Wrote: {destination_path}")


if __name__ == "__main__":
    main()
