import unittest
from epub2md import _chapter_filename


class ChapterFilenameTest(unittest.TestCase):
    def test_preserves_chinese_title(self):
        self.assertEqual(_chapter_filename("内容提要", 1), "01-内容提要.md")

    def test_issue_chapter_titles(self):
        titles = [
            "内容提要",
            "赞誉",
            "第一部分 行研框架篇",
            "第二部分 行研实战篇",
            "第三部分 研究方法篇",
            "第四部分 研究工具篇",
            "结语 一切仍没有结束",
            "致谢",
            "附录 名词解释",
            "版权声明",
        ]
        expected = [
            "01-内容提要.md",
            "02-赞誉.md",
            "03-第一部分-行研框架篇.md",
            "04-第二部分-行研实战篇.md",
            "05-第三部分-研究方法篇.md",
            "06-第四部分-研究工具篇.md",
            "07-结语-一切仍没有结束.md",
            "08-致谢.md",
            "09-附录-名词解释.md",
            "10-版权声明.md",
        ]
        self.assertEqual(
            [_chapter_filename(title, i) for i, title in enumerate(titles, 1)],
            expected,
        )

    def test_strips_filesystem_unsafe_chars_but_keeps_unicode(self):
        self.assertEqual(_chapter_filename("第1章: 研究/方法?", 2), "02-第1章-研究-方法.md")

    def test_falls_back_to_untitled_for_blank_title(self):
        self.assertEqual(_chapter_filename("   ", 3), "03-untitled.md")

    def test_normalizes_decomposed_unicode(self):
        self.assertEqual(_chapter_filename("Cafe\u0301", 4), "04-café.md")

    def test_preserves_combining_marks(self):
        self.assertEqual(_chapter_filename("नमस्ते", 5), "05-नमस्ते.md")

    def test_preserves_existing_ascii_slug_behavior(self):
        self.assertEqual(_chapter_filename("Hello_World", 6), "06-hello-world.md")

    def test_limits_filename_by_utf8_bytes(self):
        filename = _chapter_filename("\U00020000" * 80, 7)
        self.assertLessEqual(len(filename.encode("utf-8")), 255)
        self.assertEqual(filename, f"07-{'𠀀' * 62}.md")
