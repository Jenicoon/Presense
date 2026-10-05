"""Small reproducible report input for tests and local inspection."""

import json

from .report_schema import ReviewRequest


def sample_request() -> ReviewRequest:
    segments = []
    for index, (stress, pitch, pitch_std, brow) in enumerate([
        (.30, 120, 18, .10), (.32, 122, 19, .11), (.34, 124, 20, .12),
        (.82, 169, 29, .55), (.84, 165, 30, .58),
    ]):
        segments.append({
            "segmentId": f"demo-{index}", "startMs": index * 10_000,
            "endMs": (index + 1) * 10_000, "stressScore": stress,
            "predictionConfidence": max(stress, 1 - stress),
            "concepts": {"음성 피치": .2 if index < 3 else .6},
            "audioFeatures": {"f0_mean": pitch, "f0_std": pitch_std},
            "videoFeatures": {"brow_tension": brow},
            "quality": {"audioValid": True, "faceDetected": True},
        })
    return ReviewRequest(sessionId="demo-report", durationMs=50_000,
                         sceneLabel="camera", segments=segments)


if __name__ == "__main__":
    from .report_agent import generate_report

    print(json.dumps(generate_report(sample_request()), ensure_ascii=False, indent=2))
