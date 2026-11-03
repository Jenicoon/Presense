"""Plain-language coaching from saved observations, with no inferred delivery errors."""

from math import isfinite

from .coaching_methods import profile, V2_GUIDANCE


def clock(ms):
    seconds = int(ms / 1000)
    return f"{seconds // 60:02}:{seconds % 60:02}"


def guidance(finding, ko):
    rows = finding.get("observations") or []
    first = rows[0] if rows else None
    reference = finding.get("referenceValue")
    current = first.get("value") if first else None
    comparable = all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)
        for v in (current, reference)
    )
    higher = comparable and current > reference
    lower = comparable and current < reference
    directional = higher or lower
    descriptions = {
        "pitch_change": (
            "목소리가 더 높아졌어요"
            if higher
            else "목소리가 더 낮아졌어요"
            if lower
            else "목소리 높이에 변화가 있었어요",
            "Your voice moved higher"
            if higher
            else "Your voice moved lower"
            if lower
            else "Your voice pitch changed",
            "강조가 의도대로 전달됐는지 확인하기",
            "Check whether the emphasis was intentional",
            "핵심 문장 하나에만 강조 주기",
            "Emphasize one key sentence",
            "1. 선택 구간에서 말한 내용 중 꼭 전달할 문장 하나를 고르세요.\n2. 같은 내용을 30초 말하되, 그 문장에서만 목소리에 힘을 주세요.\n3. 그 문장 뒤에 잠깐 멈추고, 나머지는 편한 목소리로 이어가세요.",
            "1. Choose one key sentence from the selected interval.\n2. Repeat the same content for 30 seconds, emphasizing only that sentence.\n3. Pause briefly after it, then continue in your comfortable voice.",
        ),
        "pitch_variability": (
            "목소리 높낮이의 변화 폭이 앞부분보다 컸어요"
            if higher
            else "목소리 높낮이의 변화 폭이 앞부분보다 작았어요"
            if lower
            else "목소리 높낮이의 변화 폭은 앞부분과 비슷했어요"
            if comparable
            else "앞부분과 목소리 높낮이의 변화 폭을 비교할 자료가 부족해요",
            "Your pitch varied more than earlier in the presentation"
            if higher
            else "Your pitch varied less than earlier in the presentation"
            if lower
            else "Your pitch varied about as much as earlier in the presentation"
            if comparable
            else "There is not enough data to compare pitch variation with earlier in the presentation",
            "강조할 문장이 잘 구분되는지 듣기",
            "Listen for a clear emphasis",
            "같은 문장을 두 가지 강조로 말하기",
            "Try two ways of emphasizing a sentence",
            "1. 전달할 문장 하나를 고르세요.\n2. 15초 동안 평소처럼 말한 뒤, 15초 동안 핵심 단어 하나를 강조해 다시 말하세요.\n3. 녹음을 듣고 어느 쪽이 뜻을 더 잘 전달하는지 고르세요.",
            "1. Choose a sentence.\n2. Say it naturally for 15 seconds, then repeat for 15 seconds emphasizing one key word.\n3. Listen back and choose the version that better expresses your intention.",
        ),
        "brow_tension": (
            "눈썹이 앞부분보다 더 내려간 모습으로 측정됐어요"
            if higher
            else "눈썹이 앞부분보다 덜 내려간 모습으로 측정됐어요"
            if lower
            else "눈썹이 내려간 정도는 앞부분과 비슷했어요"
            if comparable
            else "앞부분과 눈썹 모양을 비교할 자료가 부족해요",
            "Your eyebrows were estimated to be more lowered than earlier in the presentation"
            if higher
            else "Your eyebrows were estimated to be less lowered than earlier in the presentation"
            if lower
            else "The estimated eyebrow lowering was similar to earlier in the presentation"
            if comparable
            else "There is not enough data to compare eyebrow lowering with earlier in the presentation",
            "표정이 말의 의도와 맞는지 보기",
            "Check expression against your intention",
            "핵심 메시지에 맞는 표정으로 다시 말하기",
            "Match expression to your key message",
            "1. 선택 구간을 소리와 함께 보세요.\n2. 차분함·확신·놀라움 중 전달하려던 느낌을 직접 정하세요.\n3. 같은 내용을 30초 다시 말하고 두 영상에서 표정이 의도와 맞는지 확인하세요.",
            "1. Watch the interval with sound.\n2. Choose the feeling you intended to convey, such as calm, confidence or surprise.\n3. Repeat the content for 30 seconds and compare expression against that intention.",
        ),
        "lip_tension": (
            "입이 벌어진 정도가 앞부분보다 컸어요"
            if higher
            else "입이 벌어진 정도가 앞부분보다 작았어요"
            if lower
            else "입이 벌어진 정도는 앞부분과 비슷했어요"
            if comparable
            else "앞부분과 입이 벌어진 정도를 비교할 자료가 부족해요",
            "Your mouth was more open than earlier in the presentation"
            if higher
            else "Your mouth was less open than earlier in the presentation"
            if lower
            else "Your mouth opening was similar to earlier in the presentation"
            if comparable
            else "There is not enough data to compare mouth opening with earlier in the presentation",
            "말소리가 또렷하게 들리는지 듣기",
            "Listen for clear speech",
            "전달할 문장을 나눠 다시 말하기",
            "Break a sentence into clear phrases",
            "1. 선택 구간을 듣고 스스로 전달이 흐린 문장을 고르세요.\n2. 그 문장을 뜻 단위로 나누고, 사이에 잠깐 멈추세요.\n3. 30초 다시 말한 뒤 실제 소리가 더 분명해졌는지 들어보세요.",
            "1. Listen and choose a sentence you find unclear.\n2. Divide it into meaningful phrases and pause briefly between them.\n3. Repeat for 30 seconds and listen back for clearer delivery.",
        ),
        "gaze": (
            "카메라 기준 시선 움직임에 차이가 있었어요",
            "The camera's gaze estimate changed",
            "시선이 전달 의도와 맞는지 보기",
            "Review whether gaze matches your intention",
            "핵심 문장을 말할 때 카메라 바라보기",
            "Look toward the camera for the key sentence",
            "1. 핵심 문장 하나를 고르세요.\n2. 같은 카메라 위치에서 30초 발표하며 그 문장을 말할 때 카메라를 바라보세요.\n3. 나머지 시선 이동은 자연스럽게 하고, 영상으로 의도와 맞는지 확인하세요.",
            "1. Choose a key sentence.\n2. Present for 30 seconds with the same camera position, looking toward it for that sentence.\n3. Keep other gaze shifts natural and review the recording against your intention.",
        ),
    }
    values = descriptions.get(
        finding.get("id"),
        (
            "발표 중 관측값에 변화가 있었어요",
            "An observed measurement changed",
            "선택 구간의 전달을 확인하기",
            "Review delivery in the selected interval",
            "한 가지 전달 목표로 다시 발표하기",
            "Repeat with one delivery goal",
            "1. 선택 구간을 보세요.\n2. 직접 개선할 행동 하나를 고르세요.\n3. 같은 내용을 30초 다시 발표하고 두 영상을 비교하세요.",
            "1. Review the selected interval.\n2. Choose one delivery action yourself.\n3. Repeat the content for 30 seconds and compare recordings.",
        ),
    )
    if finding.get("id") in V2_GUIDANCE:
        view = V2_GUIDANCE[finding["id"]]
        text = view["higher" if higher else "lower" if lower else "same" if comparable else "missing"]
        values = (text[0],text[1],*view["title"],*view["goal"],*view["instruction"])
    observation = values[0 if ko else 1]
    if first:
        span = f"{clock(first['startMs'])}–{clock(first['endMs'])}"
        observation = (
            f"{span}, 앞부분과 비교해 {observation[0].lower() + observation[1:]}"
            if ko and finding.get("id") == "pitch_change" and directional
            else (
                f"{span}, {observation}"
                if ko
                else f"In {span}, {observation[0].lower() + observation[1:]}"
                + (
                    " compared with earlier intervals."
                    if finding.get("id") == "pitch_change" and directional
                    else "."
                )
            )
        )
    if ko:
        observation += "."
    if not first:
        observation = (
            "이 항목의 상세 관측 자료가 없습니다."
            if ko
            else "No detailed observations are saved for this finding."
        )
    # Counts in the main copy refer only to actual available video cards. Detailed
    # evidence retains the independently counted measurements and completeness flags.
    if len(rows) > 1:
        observation += (
            f" 함께 확인할 영상은 {len(rows)}곳이에요."
            if ko
            else f" There are {len(rows)} recorded intervals to review together."
        )
    question = profile(finding)["check"][0 if ko else 1]
    return {
        "observation": observation,
        "title": values[2 if ko else 3],
        "goal": values[4 if ko else 5],
        "instruction": values[6 if ko else 7],
        "question": question,
    }


def _session_summary_without_baseline(report, ko):
    findings = report.get("priorities") or []
    if findings:
        view = guidance(findings[0], ko)
        return view["observation"] + " " + view["question"]
    if report.get("analysis", {}).get("coverage", 0) < 0.5:
        return (
            "분석된 시간이 부족해 이번 발표의 개선점을 고르기 어렵습니다. 카메라와 마이크를 확인하고 조금 더 길게 발표해 주세요."
            if ko
            else "Too little of this presentation was analyzed to select a practice focus. Check the camera and microphone and present for a little longer."
        )
    return (
        "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다. 지금의 발표 흐름을 유지하며 영상을 통해 잘 전달된 부분을 확인해 보세요."
        if ko
        else "No repeatedly observed major issue was found in this session. Keep your current approach and review the recording for what came across well."
    )


def session_summary(report, ko):
    from .baseline import baseline_sentence
    comparison = report.get("baselineComparison") or report.get("observationReport", {}).get("personalBaseline") or {}
    if comparison and "status" not in comparison:
        comparison = {**comparison, "status": "available", "observedMs": comparison["sampleCount"] * 10000}
    return " ".join(part for part in (baseline_sentence(comparison, ko), _session_summary_without_baseline(report, ko)) if part)
