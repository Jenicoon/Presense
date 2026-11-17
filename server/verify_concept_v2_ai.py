"""Opt-in real-provider check using invented data only, with exact egress audit.

This utility does not accept media, saved sessions, inference output, datasets,
feature caches or participant samples. An interrupted audit may resume only
its exact hardcoded synthetic fixture. All seven measurements are constants
written below; no checkpoint or empirical distribution is read. Only the API
key and optional local paper index are loaded. Audit files contain no headers.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from agent import report_agent
from agent.coach_ai import PROMPT, VERIFY_PROMPT, coaching_prompt, respond_with_ai
from agent.coaching import CoachRequest, new_document
from agent.model_contract import CONCEPT_VERSION, METRIC_VERSION
from agent.report_schema import ReviewRequest

NOTICE = (
    "PRIVACY-SAFE SYNTHETIC TEST: all supplied session measurements and scores "
    "were invented as constants for this test. No video/audio or person exists "
    "behind these measurements. Do not describe them as actual recorded evidence. "
    "Practice is a proposed task only. Paper excerpts are interpretation context. "
    "Apply the normal analysis workflow to the test values, so repeated changes "
    "can be inspected without implying a real person. An initially empty "
    "finishEligibleCandidateIds means no candidate has been checked yet, not "
    "that no candidate can be reviewed."
)


def synthetic_request(*, stable=False):
    """Fresh, unlinked IDs; relative times; deliberately invented constants."""
    windows = []
    for n in range(6):
        changed = not stable and n >= 2
        windows.append(
            {
                "segmentId": str(uuid4()),
                "startMs": n * 10000,
                "endMs": (n + 1) * 10000,
                "stressScore": 0.6 if changed else 0.35,
                "predictionConfidence": 0.8,
                "audioFeatures": {
                    "egemap_f0_semitone": 30.0,
                    "egemap_jitter": 0.02,
                    "egemap_shimmer_db": 0.7,
                    "egemap_hnr_db": 8.0 if changed else 12.0,
                },
                "videoFeatures": {
                    "brow_down": 0.1,
                    "eye_squint": 0.55 if changed else 0.25,
                    "jaw_open": 0.12 if changed else 0.06,
                },
                "concepts": {},
                "quality": {"audioValid": True, "faceDetected": True},
                "modelVersion": "exact7-v2-synthetic-validation",
                "metricDefinitionVersion": METRIC_VERSION,
                "conceptDefinitionVersion": CONCEPT_VERSION,
            }
        )
    return ReviewRequest(
        sessionId=str(uuid4()),
        durationMs=60000,
        sceneLabel="synthetic_test",
        segments=windows,
    )


class MinimalPaperRAG:
    """Retrieve locally, export one short relevant excerpt per paper, no filenames."""

    def __init__(self, directory):
        from agent.rag_db import PaperRAG

        self.rag = PaperRAG(db_path=directory, sync=False)
        self.excerpts = {}

    def retrieve_issue_evidence(self, issue_id, query, k=3):
        output = []
        pattern = report_agent._EVIDENCE_TERMS.get(issue_id)
        for hit in self.rag.retrieve_issue_evidence(issue_id, query, k=k):
            doi = hit.get("doi")
            if not doi or not pattern:
                continue
            if doi not in self.excerpts:
                match = pattern.search(hit["text"])
                if not match:
                    continue
                # At most 24 words, around the matching feature, not a PDF/chunk.
                preceding = hit["text"][: match.start()].split()[-5:]
                following = hit["text"][match.start() :].split()[:19]
                self.excerpts[doi] = {
                    **hit,
                    "id": "paper-" + str(uuid4()),
                    "source": "https://doi.org/" + doi,
                    "articleUrl": "https://doi.org/" + doi,
                    "text": " ".join(preceding + following),
                    "scope": " ".join((hit.get("scope") or "").split()[:24]),
                    "findingKo": (hit.get("findingKo") or "")[:160],
                }
            safe = self.excerpts[doi]
            if pattern.search(safe["text"]):
                output.append(safe)
        return output


class SyntheticAudit:
    """Persist the exact outgoing JSON before network access; reject private fields."""

    def __init__(self, directory, session_ids):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.session_ids = set(session_ids)
        self.calls = 0

    def validate(self, payload):
        context = json.loads(payload["messages"][1]["content"])
        if context.get("dataOrigin") != "synthetic":
            raise ValueError(
                "Only explicitly synthetic context may leave this verifier"
            )
        blocked_keys = {
            "email",
            "name",
            "full_name",
            "accountId",
            "userId",
            "mediaPath",
            "filename",
            "fileName",
            "frames",
            "audio",
            "video",
            "apiKey",
            "apikey",
        }

        def visit(value):
            if isinstance(value, dict):
                if blocked_keys.intersection(value):
                    raise ValueError("Private/raw-media field in outbound context")
                for key, child in value.items():
                    if (
                        key in {"sessionId", "attemptSessionId", "previousSessionId"}
                        and child
                        and child not in self.session_ids
                    ):
                        raise ValueError(
                            "Non-test session identifier in outbound context"
                        )
                    if key == "dataOrigin" and child != "synthetic":
                        raise ValueError("Non-synthetic provenance")
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                if re.search(
                    r"/Users/|/private/|/tmp/|\.(?:pdf|mp4|mov|wav|webm)\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
                    value,
                    re.IGNORECASE,
                ):
                    raise ValueError(
                        "Filename, local path or account address in outbound context"
                    )

        visit(context)

    def post(self, original, url, **kwargs):
        if url != "https://bridge.luxiacloud.com/luxia/v1/chat":
            raise ValueError("Unexpected endpoint")
        payload = kwargs["json"]
        self.validate(payload)
        self.calls += 1
        stem = self.directory / f"call-{self.calls:03}"
        stem.with_suffix(".request.json").write_text(
            json.dumps(
                {"endpoint": url, "payload": payload}, ensure_ascii=False, indent=2
            )
        )
        response = original(url, **kwargs)
        stem.with_suffix(".response.json").write_text(
            json.dumps(
                {"status": response.status_code, "body": response.json()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return response


def run(args):
    import requests
    from dotenv import load_dotenv

    load_dotenv(args.env_file)
    changed = synthetic_request()
    stable = synthetic_request(stable=True)
    resumed_report = None
    if args.resume_synthetic_audit:
        source = Path(args.resume_synthetic_audit)
        original = json.loads((source / "synthetic-input.json").read_text())
        if not original["provenance"].startswith("PRIVACY-SAFE SYNTHETIC TEST:"):
            raise ValueError("Not an audit generated by this synthetic verifier")
        restored = ReviewRequest.model_validate(original["changed"])

        def without_ids(req):
            result = req.model_dump(exclude={"sessionId"})
            for row in result["segments"]:
                row.pop("segmentId")
            return result

        if without_ids(restored) != without_ids(changed):
            raise ValueError("Only the exact hardcoded synthetic fixture may resume")
        if any(
            UUID(identity).version != 4
            for identity in [
                restored.sessionId,
                *[r.segmentId for r in restored.segments],
            ]
        ):
            raise ValueError("Expected temporary random synthetic IDs")
        resumed_report = json.loads((source / "report.json").read_text())
        if (
            resumed_report["rawSegments"] != restored.model_dump()["segments"]
            or resumed_report["modelVersion"] != restored.modelVersion
        ):
            raise ValueError("Saved report does not belong to this synthetic fixture")
        changed = restored
    audit = SyntheticAudit(args.output_dir, [changed.sessionId, stable.sessionId])
    original_post = requests.post
    original_luxia = report_agent._luxia_json
    requests.post = lambda url, **kw: audit.post(original_post, url, **kw)

    def synthetic_luxia(prompt, context, max_tokens, read_timeout=45):
        return original_luxia(
            NOTICE
            + "\n\n"
            + (coaching_prompt(context) if prompt == PROMPT else prompt),
            {**context, "dataOrigin": "synthetic", "testNotice": NOTICE},
            max_tokens,
            max(60, read_timeout),
        )

    report_agent._luxia_json = synthetic_luxia
    rag = MinimalPaperRAG(args.rag_dir) if args.rag_dir else None

    def save(name, value):
        (audit.directory / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2)
        )

    save(
        "synthetic-input.json",
        {
            "provenance": NOTICE,
            "changed": changed.model_dump(),
            "stable": stable.model_dump(),
        },
    )
    try:
        report = resumed_report or report_agent.generate_report(
            changed,
            rag=rag,
            decide=report_agent.luxia_decide_action,
            synthesize=report_agent.luxia_synthesize,
            model_version=changed.modelVersion,
            agent_mode=True,
        )
        save("report.json", report)
        if not report["priorities"]:
            raise AssertionError(
                "AI did not choose any supported synthetic finding; inspect audit"
            )
        finding = report["priorities"][0]["id"]
        doc = new_document(changed, report, changed.modelVersion)
        doc["snapshot"]["dataOrigin"] = "synthetic"
        responses = []
        for action in ("explain_finding", "create_practice"):
            doc, response = respond_with_ai(
                doc,
                CoachRequest(
                    sessionId=changed.sessionId,
                    findingId=finding,
                    action=action,
                    revision=doc["revision"],
                ),
                generate=lambda c: synthetic_luxia(PROMPT, c, 2600, 35),
                verify=lambda c: synthetic_luxia(VERIFY_PROMPT, c, 160, 15),
            )
            responses.append(response)
            save("coaching.json", {"responses": responses, "document": doc})
            assert response["generation"]["source"] == "ai"
            assert response["generation"]["validated"] is True
            assert response["generation"]["dataOrigin"] == "synthetic"
        assert doc["state"]["stage"] == "practice_created"
        stable_report = report_agent.generate_report(
            stable,
            rag=rag,
            decide=report_agent.luxia_decide_action,
            model_version=stable.modelVersion,
            agent_mode=True,
        )
        save("stable-report.json", stable_report)
        assert stable_report["priorities"] == []
        result = {
            "dataOrigin": "synthetic",
            "provider": "luxia",
            "calls": audit.calls,
            "selectedFindingIds": [f["id"] for f in report["priorities"]],
            "coachStage": doc["state"]["stage"],
            "stableFindingCount": 0,
            "rawMediaSent": False,
            "participantDataSent": False,
        }
        save("result.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        requests.post = original_post
        report_agent._luxia_json = original_luxia


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        required=True,
        help="Local API-key file; never included in requests",
    )
    parser.add_argument(
        "--rag-dir", help="Optional local paper index (no participant data)"
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="New directory for exact request/response audit",
    )
    parser.add_argument(
        "--resume-synthetic-audit",
        help="Resume only this verifier's exact hardcoded synthetic fixture; participant samples are rejected",
    )
    run(parser.parse_args())
