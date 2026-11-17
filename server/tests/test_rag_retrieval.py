"""Keep evidence search useful when a large paper contributes many nearby chunks."""
import json
import unittest
from pathlib import Path

from agent.rag_db import PaperRAG
from ai.concept_registry import PROPOSED_CONCEPTS_V2


class FakeCollection:
    def count(self):
        return 8

    def query(self, **kwargs):
        assert kwargs["n_results"] == 8
        sources = ["voice.pdf"] * 5 + ["facial.pdf"] * 2 + ["distant.pdf"]
        return {
            "ids": [[f"chunk-{i}" for i in range(8)]],
            "documents": [[f"Excerpt {i}" for i in range(8)]],
            "metadatas": [[{"source": source, "page": 1, "chunk": i} for i, source in enumerate(sources)]],
            "distances": [[.2, .21, .22, .23, .24, .3, .31, .8]],
        }


class TopicCollection(FakeCollection):
    def query(self, **kwargs):
        assert kwargs["where"] == {"topic_brow_tension": True}
        result = super().query(**kwargs)
        result["metadatas"][0][0].update({
            "title": "Brow movement study", "article_url": "https://example.org/paper",
            "doi": "10.1234/example", "scope": "Conversation, not a stress diagnosis.",
            "topics": "brow_tension,practice",
            "finding_ko": "논문의 일반 요약입니다.",
            "finding_ko_by_issue": '{"brow_tension":"눈썹 움직임에 관한 요약입니다."}',
        })
        return result


class ConceptTopicCollection(FakeCollection):
    def query(self, **kwargs):
        assert kwargs["where"] == {"topic_concept_mean_f0": True}
        result = super().query(**kwargs)
        result["metadatas"][0][0].update({
            "topics": "concept_mean_f0",
            "finding_ko": "일반 요약",
            "finding_ko_by_issue": '{"concept_mean_f0":"F0 관련 요약"}',
            "applicability": "related",
            "applicability_by_issue": '{"concept_mean_f0":"direct"}',
        })
        return result


class RagRetrievalTests(unittest.TestCase):
    def test_each_v2_concept_has_more_than_one_curated_source(self):
        source_path = Path(__file__).resolve().parents[2] / "data" / "papers" / "sources.json"
        sources = json.loads(source_path.read_text(encoding="utf-8"))
        self.assertTrue(all(
            row.get("evidence_role", "measurement")
            in {"measurement", "practice_general", "practice_specific"}
            for row in sources
        ))
        for concept in PROPOSED_CONCEPTS_V2:
            related = [row for row in sources if concept.research_topic in row.get("topics", [])]
            self.assertGreaterEqual(
                len(related), 2,
                f"{concept.research_topic} needs observation from more than one curated source",
            )

    def test_overfetch_preserves_more_than_one_relevant_paper(self):
        rag = PaperRAG.__new__(PaperRAG)
        rag._collection = FakeCollection()
        hits = rag.retrieve_evidence("speaking stress", k=4, max_distance=.45)
        self.assertEqual([hit["source"] for hit in hits],
                         ["voice.pdf", "voice.pdf", "facial.pdf", "facial.pdf"])
        self.assertTrue(all(hit["distance"] <= .45 for hit in hits))

    def test_issue_search_keeps_provenance_and_curated_topic(self):
        rag = PaperRAG.__new__(PaperRAG)
        rag._collection = TopicCollection()
        hits = rag.retrieve_issue_evidence("brow_tension", "brow movement", k=4)
        hit = hits[0]
        self.assertEqual(hit["title"], "Brow movement study")
        self.assertEqual(hit["articleUrl"], "https://example.org/paper")
        self.assertEqual(hit["topics"], ["brow_tension", "practice"])
        self.assertEqual(hit["findingKo"], "눈썹 움직임에 관한 요약입니다.")
        self.assertEqual([item["source"] for item in hits],
                         ["voice.pdf", "facial.pdf", "distant.pdf"])

    def test_concept_topic_uses_issue_specific_applicability(self):
        rag = PaperRAG.__new__(PaperRAG)
        rag._collection = ConceptTopicCollection()
        hit = rag.retrieve_issue_evidence(
            "concept_mean_f0", "stress fundamental frequency", k=1)[0]
        self.assertEqual(hit["findingKo"], "F0 관련 요약")
        self.assertEqual(hit["applicability"], "direct")


if __name__ == "__main__":
    unittest.main()
