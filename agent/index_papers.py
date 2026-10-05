"""Build the page-aware Chroma paper index before serving reports."""
from pathlib import Path
from .rag_db import PaperRAG


def main():
    papers = Path(__file__).resolve().parents[1] / "data" / "papers"
    if not list(papers.glob("*.pdf")):
        raise SystemExit(f"Place research PDFs in {papers} before indexing.")
    rag = PaperRAG(papers_dir=papers, sync=True)
    print(f"Indexed {rag._collection.count()} excerpts")


if __name__ == "__main__":
    main()
