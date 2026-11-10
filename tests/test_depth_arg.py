import sys
import unittest
from unittest.mock import patch

from epub2md import main


class DepthArgTest(unittest.TestCase):
    def test_depth_without_value_fails_cleanly(self):
        with patch.object(sys, "argv", ["epub2md", "dummy.epub", "--depth"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertIn("--depth requires an integer value", str(ctx.exception.code))

    def test_depth_with_non_integer_fails_cleanly(self):
        with patch.object(sys, "argv", ["epub2md", "dummy.epub", "--depth", "abc"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
        self.assertIn("--depth requires an integer value", str(ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
