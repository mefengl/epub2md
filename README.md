# epub2md

Convert EPUB to clean Markdown chapters.

## Install

```bash
pip install epub2md
```

## Usage

```bash
epub2md book.epub          # Creates book/*.md and book/images/
epub2md book.epub output   # Creates output/*.md and output/images/
```

Output:
```
book/
├── 01-chapter-i.md
├── 02-chapter-ii.md
├── ...
└── images/
    └── *.jpeg
```

> Images are git-ignored by default. To commit them: `rm book/images/.gitignore`

## Requirements

- Python 3.8+
- [pandoc](https://pandoc.org/installing.html)

## License

MIT
