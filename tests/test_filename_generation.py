import unittest
from epub2md import _chapter_filename


class ChapterFilenameTest(unittest.TestCase):
    def test_preserves_chinese_title(self):
        self.assertEqual(_chapter_filename("内容提要", 1), "01-内容提要.md")

    def test_strips_filesystem_unsafe_chars_but_keeps_unicode(self):
        self.assertEqual(_chapter_filename("第1章: 研究/方法?", 2), "02-第1章-研究-方法.md")

    def test_falls_back_to_untitled_for_blank_title(self):
        self.assertEqual(_chapter_filename("   ", 3), "03-untitled.md")
