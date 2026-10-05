"""
PreSense RAG 논문 DB (ChromaDB 로컬).

사용법:
  data/papers/ 에 PDF 파일을 넣으면
  PaperRAG() 초기화 시 새 파일만 자동으로 파싱·청킹·임베딩.
  이미 처리된 파일은 재처리하지 않음.
"""

from __future__ import annotations
import json
import os
import re
from pathlib import Path

_PAPERS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'papers'
_DB_PATH    = Path(os.getenv('PRESENSE_RAG_DB_PATH', str(Path(__file__).resolve().parent.parent / 'data' / 'rag_db')))

CHUNK_SIZE    = 220  # words; short enough for the embedding model to see most of the excerpt
CHUNK_OVERLAP = 40   # words
PARSER_VERSION = 5
# In two-column PDFs, text extraction may append the right-column heading
# to an unrelated left-column sentence on the same line.
_REFERENCE_HEADING = re.compile(r"(?im)(?:^|\s)(?:references|bibliography)\s*$")
_ISSUE_TOPICS = ("pitch_change", "pitch_variability", "lip_tension", "brow_tension", "gaze")


def _chunk(text: str) -> list[str]:
    words = text.split()
    step = CHUNK_SIZE - CHUNK_OVERLAP
    return [' '.join(words[i:i + CHUNK_SIZE]) for i in range(0, len(words), step)
            if len(words[i:i + CHUNK_SIZE]) > 20]


def _extract_page_text(page, source: dict, page_number: int) -> str:
    """Read curated two-column papers in column order instead of row order."""
    if source.get('layout') == 'two_column_after_first_page' and page_number > 1:
        midpoint = page.width / 2
        left = page.crop((0, 0, midpoint, page.height)).extract_text(x_tolerance=1) or ''
        right = page.crop((midpoint, 0, page.width, page.height)).extract_text(x_tolerance=1) or ''
        return f'{left}\n{right}'
    return page.extract_text(x_tolerance=1) or ''


# ── PaperRAG ─────────────────────────────────────────────────────────────────

class PaperRAG:
    """
    ChromaDB 기반 발표 스트레스 논문 검색기.

    초기화 시 data/papers/ 의 새 파일만 자동 처리.
    이미 DB에 있는 파일은 스킵.

    사용:
        rag = PaperRAG()
        papers = rag.retrieve("voice instability anxiety", k=3)
    """

    def __init__(self, db_path: str | Path | None = None,
                 papers_dir: str | Path | None = None, sync: bool = True):
        import chromadb

        Path(db_path or _DB_PATH).mkdir(parents=True, exist_ok=True)
        self._client     = chromadb.PersistentClient(path=str(db_path or _DB_PATH))
        self._collection = self._client.get_or_create_collection(
            name='stress_papers_v2',
            metadata={'hnsw:space': 'cosine'},
        )

        if sync:
            self._sync(Path(papers_dir) if papers_dir else _PAPERS_DIR)

    def _sync(self, papers_dir: Path):
        """Synchronize PDFs and curated provenance metadata with the local index."""
        if not papers_dir.exists():
            print(f"⚠️  data/papers/ 없음 — RAG DB 비어 있음")
            return

        files = sorted(papers_dir.glob('*.pdf'))
        if not files:
            print(f"⚠️  data/papers/ 에 논문 없음")
            return

        manifest_path = papers_dir / 'sources.json'
        manifest = {item['file']: item for item in json.loads(manifest_path.read_text(encoding='utf-8'))} if manifest_path.exists() else {}
        # Match indexed excerpts by PDF bytes, parser version, and provenance metadata.
        existing = {}
        indexed = self._collection.get(include=['metadatas'])
        for identity, meta in zip(indexed['ids'], indexed['metadatas']):
            existing.setdefault(meta['source'], []).append((identity, meta.get('sha256'),
                                                               meta.get('parser_version'),
                                                               meta.get('source_metadata_sha256')))

        import hashlib
        digests = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        source_digests = {path.name: hashlib.sha256(
            json.dumps(manifest.get(path.name, {}), sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest() for path in files}
        for source in existing.keys() - digests.keys():
            self._collection.delete(ids=[identity for identity, _, _, _ in existing[source]])
            print(f"  Removed missing paper: {source}")
        new_files = [path for path in files if path.name not in existing
                     or any(sha != digests[path.name] or version != PARSER_VERSION
                            or metadata_sha != source_digests[path.name]
                            for _, sha, version, metadata_sha in existing[path.name])]
        if not new_files:
            print(f"✅ RAG DB 최신 상태 ({self._collection.count()}개 청크, {len(files)}편)")
            return

        print(f"📄 새 논문 {len(new_files)}편 추가 중...")
        for path in new_files:
            try:
                import pdfplumber
                documents, metadata, ids = [], [], []
                digest = digests[path.name][:16]
                source = manifest.get(path.name, {})
                with pdfplumber.open(path) as pdf:
                    in_references = False
                    for page_number, page in enumerate(pdf.pages, start=1):
                        if in_references:
                            break
                        page_text = _extract_page_text(page, source, page_number)
                        reference_start = _REFERENCE_HEADING.search(page_text)
                        if reference_start:
                            page_text = page_text[:reference_start.start()]
                            in_references = True
                        for chunk_number, chunk in enumerate(_chunk(page_text)):
                            documents.append(chunk)
                            metadata.append({
                                'source': path.name, 'page': page_number, 'chunk': chunk_number,
                                'sha256': digests[path.name], 'parser_version': PARSER_VERSION,
                                'source_metadata_sha256': source_digests[path.name],
                                'title': source.get('title', path.stem),
                                'article_url': source.get('article_url', ''),
                                'doi': source.get('doi', ''),
                                'scope': source.get('scope', ''),
                                'finding_ko': source.get('finding_ko', ''),
                                'finding_ko_by_issue': json.dumps(source.get('finding_ko_by_issue', {}), ensure_ascii=False),
                                'evidence_role': source.get('evidence_role', 'measurement'),
                                'applicability': source.get('applicability', 'related'),
                                'topics': ','.join(source.get('topics', [])),
                                **{f'topic_{topic}': topic in source.get('topics', []) for topic in _ISSUE_TOPICS},
                            })
                            ids.append(f"{digest}:{page_number}:{chunk_number}")
                if not documents:
                    continue
                self._collection.upsert(ids=ids, documents=documents, metadatas=metadata)
                if path.name in existing:
                    current_ids = set(ids)
                    obsolete = [identity for identity, _, _, _ in existing[path.name] if identity not in current_ids]
                    if obsolete:
                        self._collection.delete(ids=obsolete)
                print(f"  ✅ {path.name} ({len(documents)}개 청크)")
            except Exception as e:
                print(f"  ⚠️  {path.name} 처리 실패: {e}")

        print(f"RAG DB: 총 {self._collection.count()}개 청크")

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        """쿼리와 유사한 논문 발췌 k개 반환."""
        if self._collection.count() == 0:
            return []
        results = self._collection.query(
            query_texts=[query],
            n_results=min(k, self._collection.count()),
        )
        return results['documents'][0] if results['documents'] else []


    def retrieve_evidence(self, query: str, k: int = 3, max_distance: float | None = None,
                          topic: str | None = None, max_per_source: int = 2) -> list[dict]:
        """Return page-linked excerpts, optionally restricted to curated issue scope."""
        count = self._collection.count()
        if not count or k <= 0:
            return []
        # Search more broadly than the final result count so one long PDF
        # cannot occupy every slot when the corpus grows.
        options = {'query_texts': [query], 'n_results': min(k * 20, count),
                   'include': ['documents', 'metadatas', 'distances']}
        if topic in _ISSUE_TOPICS:
            options['where'] = {f'topic_{topic}': True}
        results = self._collection.query(**options)
        output = []
        per_source = {}
        for identity, document, metadata, distance in zip(
            results['ids'][0], results['documents'][0],
            results['metadatas'][0], results['distances'][0],
        ):
            source = metadata['source']
            if (max_distance is None or distance <= max_distance) and per_source.get(source, 0) < max_per_source:
                output.append({'id': identity, 'text': document,
                               'source': source, 'page': metadata.get('page'),
                               'chunk': metadata['chunk'], 'distance': distance,
                               'title': metadata.get('title') or source,
                               'articleUrl': metadata.get('article_url') or None,
                               'doi': metadata.get('doi') or None,
                               'scope': metadata.get('scope') or None,
                               'findingKo': (json.loads(metadata.get('finding_ko_by_issue') or '{}').get(topic)
                                             if topic else None) or metadata.get('finding_ko') or None,
                               'evidenceRole': metadata.get('evidence_role') or 'measurement',
                               'applicability': metadata.get('applicability') or 'related',
                               'topics': (metadata.get('topics') or '').split(',') if metadata.get('topics') else []})
                per_source[source] = per_source.get(source, 0) + 1
                if len(output) == k:
                    break
        return output

    def retrieve_issue_evidence(self, issue_id: str, query: str, k: int = 3) -> list[dict]:
        return self.retrieve_evidence(query, k=k, topic=issue_id, max_per_source=1)
