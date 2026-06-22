import unittest
from pathlib import Path
from unittest.mock import patch

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import sync_data


class SyncDataRecoveryTests(unittest.TestCase):
    def test_recovery_accepts_already_landed_stream_load(self):
        clean_diff = {
            "business_date": "2026-06-15",
            "source_count": 900,
            "target_count": 900,
            "source_minus_target": 0,
            "target_minus_source": 0,
        }
        with patch.object(sync_data, "bidirectional_diff", return_value=clean_diff), patch.object(
            sync_data, "insert_from_source_if_empty"
        ) as fallback:
            result = sync_data.recover_after_stream_load_failure("2026-06-15", 900)

        fallback.assert_not_called()
        self.assertEqual(result["status"], "partial_process_success")
        self.assertFalse(result["fallback_inserted"])

    def test_recovery_uses_insert_when_target_empty(self):
        empty_diff = {
            "business_date": "2026-06-15",
            "source_count": 900,
            "target_count": 0,
            "source_minus_target": 900,
            "target_minus_source": 0,
        }
        clean_diff = {
            "business_date": "2026-06-15",
            "source_count": 900,
            "target_count": 900,
            "source_minus_target": 0,
            "target_minus_source": 0,
        }
        with patch.object(sync_data, "bidirectional_diff", side_effect=[empty_diff, clean_diff]), patch.object(
            sync_data, "insert_from_source_if_empty", return_value=True
        ) as fallback:
            result = sync_data.recover_after_stream_load_failure("2026-06-15", 900)

        fallback.assert_called_once_with("2026-06-15")
        self.assertEqual(result["status"], "fallback_insert_success")
        self.assertTrue(result["fallback_inserted"])


if __name__ == "__main__":
    unittest.main()
