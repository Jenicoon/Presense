"""Download the curated, openly accessible PDF corpus in sources.json."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

PAPERS_DIR = Path(__file__).resolve().parents[1] / "data" / "papers"
MAX_PDF_BYTES = 30 * 1024 * 1024


def main() -> None:
    sources = json.loads((PAPERS_DIR / "sources.json").read_text(encoding="utf-8"))
    for paper in sources:
        filename = paper["file"]
        target = PAPERS_DIR / filename
        if target.exists():
            if target.read_bytes()[:5] != b"%PDF-":
                raise RuntimeError(f"Existing file is not a PDF: {target}")
            print(f"Already present: {filename}")
            continue
        url = paper["pdf_url"]
        if urlparse(url).scheme != "https" or Path(filename).name != filename or not filename.endswith(".pdf"):
            raise ValueError(f"Invalid paper source: {filename}")
        temporary = target.with_suffix(".pdf.download")
        try:
            subprocess.run(
                ["curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "90",
                 "--output", str(temporary), url],
                check=True,
            )
            size = temporary.stat().st_size
            if size > MAX_PDF_BYTES or size < 20_000 or temporary.read_bytes()[:5] != b"%PDF-":
                raise RuntimeError(f"Download was not a valid research PDF: {filename}")
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(target)
        print(f"Downloaded: {filename} ({size:,} bytes)")


if __name__ == "__main__":
    main()
