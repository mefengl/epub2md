# epub2md

Convert EPUB to clean Markdown chapters.

## Install

```bash
pip install epub2md
```

## Usage

```bash
epub2md book.epub          # Creates book/chapters/ and book/media/
epub2md book.epub output   # Creates output/chapters/ and output/media/
```

Output:
```
book/
├── chapters/
│   ├── 01-chapter-i.md
│   └── ...
└── media/
    └── *.jpeg
```

## Requirements

- Python 3.8+
- [pandoc](https://pandoc.org/installing.html)

## License

MIT
