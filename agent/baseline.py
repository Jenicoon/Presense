"""Initial measured reference, separate from raw session/model scores."""


def compare_baseline(request, observed, model_version):
    if request.personalBaseline is None:
        return {"status": "missing"}
    if model_version == "unknown" or request.baselineModelVersion != model_version:
        return {"status": "model_mismatch"}
    average = observed["averageStressScore"]
    peak = observed["peakSegment"]
    return {
        "status": "available", "score": request.personalBaseline,
        "sampleCount": request.baselineSampleCount, "windowMs": 10000,
        "observedMs": request.baselineSampleCount * 10000,
        "aggregation": "median", "modelVersion": model_version,
        "source": request.baselineSource or "preparation",
        "averageDifference": round(average - request.personalBaseline, 4) if average is not None else None,
        "peakDifference": round(peak["stressScore"] - request.personalBaseline, 4) if peak else None,
    }


def baseline_sentence(comparison, ko):
    if comparison.get("status") != "available":
        return ""
    score = comparison["score"] * 100
    count = comparison["sampleCount"]
    seconds = comparison["observedMs"] / 1000
    difference = comparison["averageDifference"]
    initial = (f"초기 측정 {seconds:g}초(10초 × {count})의 중앙값은 {score:.2f}/100입니다."
               if ko else f"The initial {seconds:g}s reference ({count} × 10s) has a median of {score:.2f}/100.")
    if difference is None:
        return initial
    points = abs(difference * 100)
    if points < .5:
        return initial + (" 이번 발표의 평균 스트레스 신호는 초기값과 비슷했습니다."
                          if ko else " This presentation's mean stress signal was similar to the initial reference.")
    return initial + (f" 이번 발표의 평균 스트레스 신호는 초기값보다 {points:.0f}점 {'높았습니다' if difference > 0 else '낮았습니다'}."
                      if ko else f" This presentation's mean stress signal was {points:.0f} points {'higher' if difference > 0 else 'lower'} than the initial reference.")
