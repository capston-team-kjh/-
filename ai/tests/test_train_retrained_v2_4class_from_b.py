from __future__ import annotations

import unittest

from ai.train_retrained_v2_4class_from_b import CLASSES, sample_signature


class FourClassCandidateTests(unittest.TestCase):
    def test_uses_the_required_four_class_schema(self) -> None:
        self.assertEqual(CLASSES, ("focus", "drowsy", "gaze_down", "gaze_side"))

    def test_sample_signature_includes_source_hash_timestamp_and_label(self) -> None:
        self.assertEqual(sample_signature({"source_sha256": "abc", "timestamp_sec": "1.25", "label": "focus"}), ("abc", "1.25", "focus"))


if __name__ == "__main__":
    unittest.main()
