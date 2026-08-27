import tempfile
import unittest
from pathlib import Path

from case_studies.model_6_simpy.analysis.compare_flow_trace import (
    parse_anylogic_flow_trace,
)
from case_studies.model_6_simpy.analysis.compare_rng_trace import (
    TraceBlockKey,
    parse_anylogic_trace,
    parse_anylogic_trace_blocks,
    parse_iteration_header,
)


DETERMINISTIC_BODY = (
    "t=0.0,event=source_item_count,current_nof_items=9\n"
    "t=18.75,event=unbatch_started,current_nof_items=9\n"
    "t=18.75,event=loose_items_injected,items_count=2\n"
)
REPLICATION_BODY = (
    "t=0.0,event=source_item_count,current_nof_items=7\n"
    "t=16.25,event=unbatch_started,current_nof_items=7\n"
    "t=16.25,event=loose_items_injected,items_count=5\n"
)


def _write(tmp: Path, name: str, text: str) -> Path:
    path = tmp / name
    path.write_text(text)
    return path


class IterationHeaderTests(unittest.TestCase):
    def test_distinguishes_deterministic_and_replication_headers(self):
        self.assertEqual(
            parse_iteration_header("ITERATION #1"),
            TraceBlockKey(iteration=1, replication=None),
        )
        self.assertEqual(
            parse_iteration_header("ITERATION #1, REPLICATION #7"),
            TraceBlockKey(iteration=1, replication=7),
        )

    def test_data_lines_are_not_headers(self):
        self.assertIsNone(
            parse_iteration_header("t=0.0,event=source_item_count,current_nof_items=9")
        )

    def test_unrecognized_header_raises(self):
        with self.assertRaises(ValueError):
            parse_iteration_header("ITERATION #1 EXTRA JUNK")


class TraceBlockSelectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_deterministic_block_survives_trailing_replications(self):
        """A stochastic run appends replication blocks; they must not shadow it."""
        path = _write(
            self.tmp,
            "mixed.txt",
            "ITERATION #1\n"
            + DETERMINISTIC_BODY
            + "".join(
                f"ITERATION #1, REPLICATION #{index}\n" + REPLICATION_BODY
                for index in range(1, 4)
            ),
        )
        selected = parse_anylogic_trace(path)
        self.assertEqual(sorted(selected), [1])
        self.assertEqual(
            [(pair.current_nof_items, pair.items_count) for pair in selected[1].pairs],
            [(9, 2)],
        )

    def test_replication_can_be_selected_explicitly(self):
        path = _write(
            self.tmp,
            "mixed.txt",
            "ITERATION #1\n"
            + DETERMINISTIC_BODY
            + "ITERATION #1, REPLICATION #2\n"
            + REPLICATION_BODY,
        )
        selected = parse_anylogic_trace(path, replication=2)
        self.assertEqual(
            [(pair.current_nof_items, pair.items_count) for pair in selected[1].pairs],
            [(7, 5)],
        )

    def test_all_blocks_are_retained_under_distinct_keys(self):
        path = _write(
            self.tmp,
            "mixed.txt",
            "ITERATION #1\n"
            + DETERMINISTIC_BODY
            + "ITERATION #1, REPLICATION #1\n"
            + REPLICATION_BODY,
        )
        self.assertEqual(
            sorted(key.label() for key in parse_anylogic_trace_blocks(path)),
            ["ITERATION #1", "ITERATION #1, REPLICATION #1"],
        )

    def test_deterministic_only_trace_still_parses(self):
        path = _write(
            self.tmp,
            "legacy.txt",
            "ITERATION #1\n" + DETERMINISTIC_BODY + "ITERATION #2\n" + DETERMINISTIC_BODY,
        )
        self.assertEqual(sorted(parse_anylogic_trace(path)), [1, 2])

    def test_replication_only_trace_reports_available_blocks(self):
        path = _write(
            self.tmp,
            "reps.txt",
            "".join(
                f"ITERATION #1, REPLICATION #{index}\n" + REPLICATION_BODY
                for index in range(1, 4)
            ),
        )
        with self.assertRaises(ValueError) as caught:
            parse_anylogic_trace(path)
        self.assertIn("no deterministic ITERATION block", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            parse_anylogic_trace(path, replication=99)
        self.assertIn("Available replications: 1, 2, 3", str(caught.exception))

    def test_duplicate_block_is_rejected(self):
        path = _write(
            self.tmp,
            "duplicate.txt",
            "ITERATION #1\n" + DETERMINISTIC_BODY + "ITERATION #1\n" + DETERMINISTIC_BODY,
        )
        with self.assertRaises(ValueError) as caught:
            parse_anylogic_trace(path)
        self.assertIn("more than one ITERATION #1", str(caught.exception))

    def test_flow_trace_parser_uses_the_same_block_rules(self):
        path = _write(
            self.tmp,
            "flow.txt",
            "ITERATION #1\n"
            + DETERMINISTIC_BODY
            + "ITERATION #1, REPLICATION #1\n"
            + REPLICATION_BODY,
        )
        deterministic = parse_anylogic_flow_trace(path, events=("unbatch_started",))
        replication = parse_anylogic_flow_trace(
            path,
            events=("unbatch_started",),
            replication=1,
        )
        self.assertEqual([event.time_s for event in deterministic[1]], [18.75])
        self.assertEqual([event.time_s for event in replication[1]], [16.25])


if __name__ == "__main__":
    unittest.main()
