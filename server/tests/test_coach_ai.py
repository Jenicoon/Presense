"""Grounding contracts for LLM-authored coaching. No external calls."""

import unittest
from copy import deepcopy

from agent.coach_ai import (
    AIUnavailable,
    VERIFY_PROMPT,
    build_context,
    coaching_prompt,
    respond_with_ai,
    validate_plan,
)
from agent.coaching import CoachRequest
from server.tests.test_coaching import document


def grounded_plan(context):
    action = context["request"]["action"]
    finding = context["request"].get("findingId") or context["state"].get(
        "selectedFindingId"
    )
    finding = finding or next((f["id"] for f in context["findings"]), None)
    key = f"finding.{finding}" if finding else "current.summary"
    plan = {
        "action": "explain_finding" if action == "ask" else action,
        "findingId": finding,
        "evidenceIds": [key],
        "message": {
            "ko": "{{evidence:"
            + key
            + "}} 이 변화가 의도한 강조였는지 먼저 확인해 보세요.",
            "en": "{{evidence:"
            + key
            + "}} First check whether this change was intentional emphasis.",
        },
        "videoRefs": [next(iter(context["videoRefs"]))] if context["videoRefs"] else [],
        "followUps": [],
        "practice": None,
    }
    if context["state"].get("reviewFeedback") == "intentional" or context["state"].get(
        "reviewOutcome"
    ) in {"intentional", "effective"}:
        plan["message"] = {
            "ko": "알려주신 표현은 유지하겠습니다. 원하면 아래에서 문장 경계 연습을 선택해 보세요.",
            "en": "Keep the expression you confirmed. You can optionally choose sentence boundary practice below.",
        }
    if (
        action in {"explain_finding", "guide_review"}
        and finding
        and not (
            context["state"].get("reviewFeedback") == "intentional"
            or context["state"].get("reviewOutcome") in {"intentional", "effective"}
        )
    ):
        plan["reviewGuide"] = {
            "title": {
                "ko": "이렇게 듣고 다음 행동 고르기",
                "en": "Listen and choose the next action",
            },
            "steps": [
                {
                    "ko": "구간에서 가장 중요한 문장을 직접 고르세요.",
                    "en": "Choose the key sentence yourself.",
                },
                {
                    "ko": "문장 끝의 쉼을 듣고 아래에서 연습할 행동을 고르세요.",
                    "en": "Listen for a pause at the sentence ending and choose a rehearsal action below.",
                },
            ],
        }
    if action == "create_practice" and finding:
        plan["practice"] = {
            "strategyId": context["state"].get("practiceStrategyId")
            or next(iter(context["practiceMethods"])),
            "successCheck": {
                "ko": "녹음을 듣고 의미 단위 사이에 쉼을 두었는지 직접 확인하세요.",
                "en": "Listen back and check whether you paused between meaningful phrases.",
            },
            "label": {
                "ko": "선택한 문장을 나눠 말하기",
                "en": "Rehearse a sentence in phrases",
            },
            "steps": [
                {
                    "ko": "영상에서 다시 말할 문장을 직접 골라 주세요.",
                    "en": "Choose a sentence from your recording yourself.",
                },
                {
                    "ko": "의미 단위 사이에 멈추며 같은 내용을 다시 말해 보세요.",
                    "en": "Repeat the same content with a pause between meaningful phrases.",
                },
            ],
            "durationSeconds": 30,
        }
    return plan


class CoachAIContractTests(unittest.TestCase):
    def test_no_finding_review_uses_ai_narrative_with_server_facts_and_no_forced_exercise(self):
        doc=document(changed=False)
        request=CoachRequest(sessionId='baseline',action='review')
        def generate(context):
            return {'action':'review','findingId':None,'evidenceIds':['current.summary'],
                    'message':{'ko':'선택된 교정 목표는 없습니다. 저장된 구간에 대해 질문할 수 있습니다.',
                               'en':'No correction target is selected. You can ask about the saved intervals.'},
                    'practice':None,'reviewGuide':None,'videoRefs':[],'followUps':[]}
        updated,response=respond_with_ai(doc,request,generate=generate,verify=lambda context:{'supported':True})
        self.assertEqual(response['generation']['source'],'ai')
        self.assertIn('선택된 교정 목표는 없습니다',response['message'])
        self.assertEqual(updated['practices'],[])
        self.assertFalse(any(card['type']=='practice' for card in response['components']))
        self.assertEqual(doc['messages'],[])

    def test_no_finding_prompt_allows_coaching_from_presenter_self_report(self):
        doc = document(changed=False)
        request = CoachRequest(
            sessionId="baseline",
            action="ask",
            message="중간에 대본이 생각나지 않으면 당황하게 돼",
        )
        context = build_context(doc, request)
        prompt = coaching_prompt(context)
        self.assertIn("first-person experience", prompt)
        self.assertIn("forgetting a script", prompt)
        self.assertIn("current question is a source", VERIFY_PROMPT)

        def generate(_context):
            return {
                "action": "ask",
                "findingId": None,
                "evidenceIds": [],
                "message": {
                    "ko": "말씀하신 상황에서는 문장 전체를 외우기보다 핵심 단어를 기준으로 다음 내용을 이어가는 연습이 도움이 됩니다. 멈추면 핵심 문장을 짧게 다시 말하고 다음 요점으로 넘어가 보세요.",
                    "en": "For the situation you described, rehearse from key words instead of memorizing every sentence. If you lose your place, briefly restate the key point and move to the next idea.",
                },
                "practice": None,
                "reviewGuide": None,
                "videoRefs": [],
                "followUps": [],
            }

        seen = {}

        def verify(payload):
            seen.update(payload)
            return {"supported": True}

        updated, response = respond_with_ai(
            doc, request, generate=generate, verify=verify
        )
        self.assertEqual(seen["question"], request.message)
        self.assertIn("말씀하신 상황", response["message"])
        self.assertEqual(updated["messages"][-2]["text"], request.message)

    def test_direct_previous_session_question_requires_a_measured_comparison(self):
        current = document(identity="current", changed=True)
        previous = document(identity="previous", changed=False)
        request = CoachRequest(
            sessionId="current",
            action="ask",
            message="나 지난 세션보다 괜찮아진 것과 나쁜 게 있니?",
        )
        current["messages"] = [{"role": "agent", "text": "구체적인 데이터는 제공되지 않았습니다."}]
        context = build_context(current, request, previous=previous)
        self.assertTrue(context["comparisonQuestion"])
        self.assertEqual(context["comparison"]["outcome"], "comparable")
        self.assertTrue(context["comparisonHighlights"])
        self.assertIn("comparison.selection", context["facts"])
        self.assertEqual(context["history"], [])
        self.assertEqual(
            set(context["facts"]),
            {"comparison.result", "comparison.selection", *context["comparisonHighlights"]},
        )
        metric_id = context["comparisonHighlights"][0]
        plan = {
            "action": "ask",
            "findingId": None,
            "evidenceIds": ["comparison.result", "comparison.selection", metric_id],
            "message": {
                "ko": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} 지금 방식대로 이어갈 점과 살펴볼 변화를 나누기 위해 같은 종류의 문장을 두 영상에서 직접 비교해 보세요.",
                "en": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} Review the same kind of sentence in both recordings to separate what can stay as-is from a change to check.",
            },
            "practice": None,
            "reviewGuide": None,
            "videoRefs": [],
            "followUps": [],
        }
        checked = validate_plan(plan, context)
        self.assertIn(metric_id, checked.evidenceIds)
        self.assertIn("같은 종류의 문장", checked.message.ko)
        self.assertIn("stay as-is", checked.message.en)

        sparse = deepcopy(plan)
        sparse["evidenceIds"] = ["comparison.result"]
        sparse["message"] = {
            "ko": "{{evidence:comparison.result}} 긍정적으로 이어갈 후보와 살펴볼 변화를 나누기 위해 두 녹화에서 같은 종류의 문장을 비교하세요.",
            "en": "{{evidence:comparison.result}} Review the same kind of sentence in both recordings to separate a positive carry-forward candidate from a change to check.",
        }
        normalized = validate_plan(sparse, context)
        self.assertIn(metric_id, normalized.evidenceIds)
        self.assertIn("{{evidence:" + metric_id + "}}", normalized.message.ko)

        generic = deepcopy(plan)
        generic["evidenceIds"] = ["comparison.result", "comparison.selection", metric_id]
        generic["message"] = {
            "ko": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} 지난 세션과 비교할 구체적인 데이터는 제공되지 않았습니다.",
            "en": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} No concrete data were provided for the previous-session comparison.",
        }
        with self.assertRaisesRegex(ValueError, "comparison data are missing"):
            validate_plan(generic, context)

        unrelated = deepcopy(plan)
        unrelated["message"]["ko"] += " 불안을 줄이기 위한 준비 전략을 사용하세요."
        unrelated["message"]["en"] += " Use a preparation strategy to reduce anxiety."
        with self.assertRaisesRegex(ValueError, "stay with measured differences"):
            validate_plan(unrelated, context)

        prompt = coaching_prompt(context)
        self.assertIn("comparisonHighlights", prompt)
        self.assertIn("generic confidence", prompt)

    def test_previous_session_video_measurements_are_displayed_to_two_decimals(self):
        current = document(identity="current", changed=True)
        previous = document(identity="previous", changed=False)
        for segment in previous["snapshot"]["request"]["segments"]:
            segment["videoFeatures"]["brow_tension"] = 0.256412
        for segment in current["snapshot"]["request"]["segments"]:
            segment["videoFeatures"]["brow_tension"] = 0.310715
        context = build_context(
            current,
            CoachRequest(
                sessionId="current",
                action="ask",
                message="지난 세션보다 달라진 점이 있니?",
            ),
            previous=previous,
        )
        video_facts = [
            fact["ko"]
            for identity, fact in context["facts"].items()
            if identity.startswith("comparison.metric")
        ]
        self.assertTrue(any("이전 0.26, 현재 0.31" in fact for fact in video_facts))
        self.assertFalse(any("0.256412" in fact or "0.310715" in fact for fact in video_facts))

    def test_saved_validated_comparison_is_reused_when_the_previous_record_is_no_longer_available(self):
        current = document(identity="current", changed=True)
        previous = document(identity="previous", changed=False)
        request = CoachRequest(
            sessionId="current",
            action="ask",
            message="나 지난 세션보다 괜찮아진 것과 나쁜 게 있니?",
        )

        def generate(context):
            metric_id = context["comparisonHighlights"][0]
            return {
                "action": "ask",
                "findingId": None,
                "evidenceIds": ["comparison.result", "comparison.selection", metric_id],
                "message": {
                    "ko": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} 유지할 후보와 확인할 변화를 나누기 위해 두 영상에서 같은 종류의 문장을 살펴보세요.",
                    "en": "{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:" + metric_id + "}} Review the same kind of sentence in both recordings to separate a positive carry-forward candidate from a change to check.",
                },
                "practice": None,
                "reviewGuide": None,
                "videoRefs": [],
                "followUps": [],
            }

        updated, first = respond_with_ai(
            current,
            request,
            generate=generate,
            verify=lambda _: {"supported": True},
            previous=previous,
        )
        reused, second = respond_with_ai(
            updated,
            request,
            generate=None,
            verify=None,
            previous=None,
        )
        self.assertEqual(second["message"], first["message"])
        self.assertEqual(second["generation"]["source"], "ai")
        self.assertEqual(reused["revision"], updated["revision"] + 1)
        self.assertNotIn("현재 발표:", second["message"])

    def test_legacy_comparison_facts_generate_new_ai_coaching_without_source_snapshot(self):
        current=document(identity="legacy-current",changed=True)
        generation={"source":"ai","validated":True,
                    "evidenceIds":["comparison.result","comparison.selection","comparison.metric0"]}
        ko=("같은 기준의 스트레스 신호: 이전 72 / 100, 현재 75 / 100. 이 차이는 좋고 나쁨의 결론보다 음성·영상 측정값을 함께 살펴볼 위치를 정하는 데 사용합니다. "
            "보고서에서 선택된 검토 항목: 이전 선택된 검토 항목 없음; 현재 선택된 검토 항목 없음. "
            "눈꺼풀 조임 움직임: 이전 0.26, 현재 0.31. 이전 고정 코칭 문장")
        en=("Stress signals under the same criteria: before 72 / 100, current 75 / 100. Use this difference to prioritize the voice and video measurements to review, rather than as a better-or-worse verdict. "
            "Report-selected review items: previous no selected review item; current no selected review item. "
            "Eyelid tightening movement: before 0.26, current 0.31. Old fixed coaching prose")
        current["messages"]=[{"role":"agent","text":ko,"response":{"message":ko,"generation":generation},
                              "translations":{"ko":{"response":{"message":ko,"generation":generation}},
                                              "en":{"response":{"message":en,"generation":generation}}}}]
        request=CoachRequest(sessionId="legacy-current",action="ask",message="지난 세션과 비교해서 알려줘")
        def generate(context):
            self.assertTrue(context["comparisonQuestion"])
            self.assertEqual(context["facts"]["comparison.metric0"]["ko"],"눈꺼풀 조임 움직임: 이전 0.26, 현재 0.31.")
            return {"action":"ask","findingId":None,
                    "evidenceIds":["comparison.result","comparison.selection","comparison.metric0"],
                    "message":{"ko":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:comparison.metric0}} 두 영상에서 비슷한 문장을 골라 눈 주변 움직임이 의도한 강조와 함께 나타나는지 비교하세요.",
                               "en":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:comparison.metric0}} Compare similar sentences in both recordings and review whether the eye movement accompanies intended emphasis."},
                    "practice":None,"reviewGuide":None,"videoRefs":[],"followUps":[]}
        _,response=respond_with_ai(current,request,previous=None,generate=generate,verify=lambda _: {"supported":True})
        self.assertEqual(response["generation"]["authoringVersion"],"ai-authored-comparison-v3")
        self.assertNotIn("이전 고정 코칭 문장",response["message"])
        self.assertIn("눈 주변 움직임",response["message"])

    def test_comparison_uses_retrieved_paper_fact_and_server_owned_reference(self):
        current=document(identity="research-current",changed=True)
        previous=document(identity="research-previous",changed=False)
        request=CoachRequest(sessionId="research-current",action="ask",message="지난 발표와 비교해줘")

        def retrieve(context):
            self.assertTrue(context["comparisonQuestion"])
            return [{
                "id":"paper:eye:1", "title":"Eyelid activity study",
                "articleUrl":"https://example.test/paper", "doi":"10.0000/example",
                "factKo":"관련 연구에서 AU7 눈꺼풀 조임 움직임은 주관적 반응과 연관됐지만 생리 지표는 같은 방향이 아니었습니다.",
                "factEn":"In related research, AU7 eyelid activity was associated with subjective response while physiological markers did not follow the same direction.",
                "scopeKo":"측정 해석 연구이며 연습 효과 연구는 아닙니다.",
                "scopeEn":"Measurement interpretation, not an exercise trial.",
            }, {
                "id":"paper:gaze:2", "title":"Audience gaze training trial",
                "articleUrl":"https://example.test/trial", "doi":"10.0000/trial",
                "factKo":"무작위 비교 연구에서 반복적인 청중 시선 연습을 시험했습니다.",
                "factEn":"A randomized trial tested repeated audience-gaze practice.",
                "scopeKo":"눈꺼풀 조임 교정 실험은 아닙니다.",
                "scopeEn":"Not an eyelid-tightening intervention.",
            }]

        def generate(context):
            metric_id=context["comparisonHighlights"][0]
            self.assertIn("research.0",context["facts"])
            self.assertIn("research.0",context["researchRefs"])
            self.assertIn("research.1",context["researchRefs"])
            return {"action":"ask","findingId":None,
                    "evidenceIds":["comparison.result","comparison.selection",metric_id,"research.0","research.1"],
                    "message":{"ko":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} {{evidence:research.0}} {{evidence:research.1}} 같은 조명과 카메라에서 같은 문장을 비교하세요. 원치 않은 움직임이 반복되면 렌즈나 청중 위치를 보며 같은 문장을 여러 번 말한 뒤 원본과 비교하세요.",
                               "en":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} {{evidence:research.0}} {{evidence:research.1}} Compare the same sentence with matching camera and lighting. If the unwanted movement repeats, say it several times while looking toward the lens or an audience position, then compare it with the original."},
                    "practice":None,"reviewGuide":None,"videoRefs":[],"followUps":[]}

        _,response=respond_with_ai(current,request,previous=previous,generate=generate,
                                   verify=lambda _: {"supported":True},retrieve_research=retrieve)
        self.assertNotIn("관련 연구",response["message"])
        self.assertIn("같은 조명과 카메라",response["message"])
        reference=next(card for card in response["components"] if card["type"]=="research_references")
        self.assertEqual(reference["items"][0]["title"],"Eyelid activity study")
        self.assertEqual(reference["items"][0]["finding"],retrieve({"comparisonQuestion":True})[0]["factKo"])
        self.assertEqual(reference["items"][1]["title"],"Audience gaze training trial")
        self.assertNotIn("깜빡",response["message"])

    def test_comparison_removes_restated_server_owned_research_claim(self):
        current=document(identity="research-guard-current",changed=True)
        previous=document(identity="research-guard-previous",changed=False)
        request=CoachRequest(sessionId="research-guard-current",action="ask",message="지난 발표와 비교해줘")
        context=build_context(current,request,previous=previous)
        metric_id=context["comparisonHighlights"][0]
        context["facts"]["research.0"]={"ko":"서버 논문 근거.","en":"Server research evidence."}
        context["researchRefs"]={"research.0":{"id":"paper"}}
        plan={"action":"ask","findingId":None,
              "evidenceIds":["comparison.result","comparison.selection",metric_id,"research.0"],
              "message":{"ko":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} {{evidence:research.0}} 연구에 따르면 이 움직임은 스트레스 반응을 뜻합니다. 두 영상을 비교하세요.",
                         "en":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} {{evidence:research.0}} According to the study, this movement means a stress response. Compare both recordings."},
              "practice":None,"reviewGuide":None,"videoRefs":[],"followUps":[]}
        checked=validate_plan(plan,context)
        self.assertIn("{{evidence:research.0}}",checked.message.ko)
        self.assertNotIn("연구에 따르면",checked.message.ko)
        self.assertIn("두 영상을 비교하세요",checked.message.ko)

    def test_comparison_removes_redundant_research_tail_without_failing(self):
        current=document(identity="concise-current",changed=True)
        previous=document(identity="concise-previous",changed=False)
        request=CoachRequest(sessionId="concise-current",action="ask",message="지난 발표와 비교해줘")
        context=build_context(current,request,previous=previous)
        metric_id=context["comparisonHighlights"][0]
        plan={"action":"ask","findingId":None,
              "evidenceIds":["comparison.result","comparison.selection",metric_id],
              "message":{"ko":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} 측정값의 변화를 확인해보세요. 같은 문장을 영상에서 비교하세요. 렌즈를 보며 다시 말한 뒤 원본과 비교하세요. 이런 연습이 도움이 될 수 있습니다.",
                         "en":"{{evidence:comparison.result}} {{evidence:comparison.selection}} {{evidence:"+metric_id+"}} Review the measured change. Compare the same sentence in both recordings. Repeat it toward the lens and compare it with the original. This practice may help."},
              "practice":None,"reviewGuide":None,"videoRefs":[],"followUps":[]}
        checked=validate_plan(plan,context)
        self.assertNotIn("도움이 될 수",checked.message.ko)
        self.assertNotIn("may help",checked.message.en)
        self.assertNotIn("변화를 확인",checked.message.ko)
        self.assertIn("원본과 비교",checked.message.ko)

    def setUp(self):
        self.doc = document()
        self.request = CoachRequest(sessionId="baseline", action="explain_finding")
        self.context = build_context(self.doc, self.request)

    def test_context_contains_all_window_summary_quality_and_no_credentials(self):
        ctx = self.context
        self.assertEqual(ctx["sessionSummaries"]["current"]["windowCount"], 5)
        self.assertEqual(
            ctx["sessionSummaries"]["current"]["analysis"]["observedMs"], 50000
        )
        self.assertIn("finding.pitch_change", ctx["facts"])
        self.assertIn("current.window0.audio0", ctx["facts"])
        self.assertNotIn("api_key", str(ctx).lower())
        self.assertNotIn("recommendation", ctx)
        self.assertEqual(self.doc["messages"], [])

    def test_valid_plan_uses_existing_facts_and_video_references(self):
        plan = validate_plan(grounded_plan(self.context), self.context)
        self.assertEqual(plan.findingId, "pitch_change")

    def test_invented_evidence_time_number_component_markup_and_finding_rejected(self):
        for field, value in [
            ("evidenceIds", ["made_up"]),
            ("videoRefs", ["current.window999"]),
            ("findingId", "nonexistent"),
            ("action", "start_recording"),
            (
                "message",
                {"ko": "스트레스가 90%입니다.", "en": "Your actual stress is 90%."},
            ),
            ("message", {"ko": "<script>내용</script>", "en": "<script>bad</script>"}),
        ]:
            plan = grounded_plan(self.context)
            plan[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_plan(plan, self.context)

    def test_no_forced_exercise_without_a_supported_finding(self):
        context = build_context(
            document(changed=False),
            CoachRequest(sessionId="baseline", action="create_practice"),
        )
        plan = grounded_plan(context)
        other = deepcopy(plan)
        other["practice"] = grounded_plan(
            build_context(
                self.doc, CoachRequest(sessionId="baseline", action="create_practice")
            )
        )["practice"]
        with self.assertRaises(ValueError):
            validate_plan(other, context)
        self.assertIsNone(validate_plan(plan, context).practice)

    def test_semantic_checker_cannot_approve_unmeasured_delivery_claim(self):
        plan = grounded_plan(self.context)
        plan["message"]["ko"] += " 전달이 어려웠을 수 있어요."
        with self.assertRaisesRegex(ValueError, "Unmeasured delivery"):
            validate_plan(plan, self.context)

    def test_unsafe_choice_label_uses_the_server_label_without_changing_action(self):
        def generate(context):
            plan = grounded_plan(context)
            plan["followUps"] = [
                {
                    "action": "create_practice",
                    "label": {"ko": "영상 99:99", "en": "Video <script>99:99</script>"},
                }
            ]
            return plan

        updated, response = respond_with_ai(
            self.doc,
            self.request,
            generate=generate,
            verify=lambda c: {"supported": True},
        )
        choice = next(
            c for c in response["components"] if c["type"] == "action_choices"
        )["choices"][0]
        self.assertEqual(choice["action"], "submit_review")
        self.assertNotIn("99:99", choice["label"])
        self.assertEqual(updated["revision"], 1)

    def test_model_cannot_change_explicit_selection(self):
        context = build_context(
            self.doc, self.request.model_copy(update={"findingId": "pitch_change"})
        )
        plan = grounded_plan(context)
        plan["findingId"] = None
        with self.assertRaises(ValueError):
            validate_plan(plan, context)

    def test_missing_ai_does_not_mutate_or_create_template_coaching(self):
        original = deepcopy(self.doc)
        with self.assertRaises(AIUnavailable):
            respond_with_ai(self.doc, self.request)
        self.assertEqual(self.doc, original)

    def test_injected_ai_authors_one_exercise_and_restores_both_languages(self):
        from agent.coaching import localized_messages, validate_response

        request = self.request.model_copy(update={"action": "create_practice"})
        calls = []

        def generate(context):
            calls.append(context)
            return grounded_plan(context)

        updated, response = respond_with_ai(
            self.doc, request, generate=generate, verify=lambda c: {"supported": True}
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(response["generation"]["source"], "ai")
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(len(updated["practices"]), 1)
        self.assertEqual(updated["practices"][0]["authoredBy"], "ai")
        self.assertIn("문장을 나눠", updated["practices"][0]["label"])
        self.assertEqual(updated["messages"][-1]["text"], response["message"])
        translated = localized_messages(updated, "en")[-1]["response"]
        self.assertNotRegex(str(translated), r"[가-힣]")
        self.assertEqual(
            translated["conversationState"]["activePracticeId"],
            response["conversationState"]["activePracticeId"],
        )
        validate_response(translated, updated)
        self.assertEqual(self.doc["revision"], 0)

    def test_rejected_semantic_claims_and_provider_failure_never_commit(self):
        original = deepcopy(self.doc)
        for verifier in (
            lambda c: {"supported": False, "reason": "invented cause"},
            lambda c: {},
        ):
            with self.assertRaises(AIUnavailable):
                respond_with_ai(
                    self.doc, self.request, generate=grounded_plan, verify=verifier
                )
            self.assertEqual(self.doc, original)

        def broken(context):
            raise TimeoutError("provider unavailable")

        with self.assertRaises(AIUnavailable):
            respond_with_ai(
                self.doc,
                self.request,
                generate=broken,
                verify=lambda c: {"supported": True},
            )
        self.assertEqual(self.doc, original)

    def test_invalid_user_interval_is_rejected_before_any_model_access(self):
        calls = []
        with self.assertRaises(ValueError):
            respond_with_ai(
                self.doc,
                self.request.model_copy(update={"findingId": "fake"}),
                generate=lambda c: calls.append(c),
                verify=lambda c: {"supported": True},
            )
        self.assertEqual(calls, [])


class V2ReviewCompositionTests(unittest.TestCase):
    def context(self):
        from agent.coaching import new_document
        from agent.report_agent import generate_report
        from server.tests.test_feedback_selection import measured_request
        req=measured_request(2)
        report=generate_report(req,model_version=req.modelVersion,agent_mode=True)
        doc=new_document(req,report,req.modelVersion)
        return build_context(doc,CoachRequest(sessionId=req.sessionId,action="explain_finding",findingId="v2_jitter"))

    def test_review_uses_server_facts_and_ai_guide_instead_of_untrusted_restatement(self):
        context=self.context();raw=grounded_plan(context)
        raw['message']={'ko':'없는 시점 99:99와 지어낸 값 999','en':'An invented observation at 99:99 with value 999'}
        plan=validate_plan(raw,context)
        self.assertIn('{{evidence:finding.v2_jitter}}',plan.message.ko)
        self.assertNotIn('999',plan.message.ko)
        self.assertEqual(plan.reviewGuide.steps[0].ko,raw['reviewGuide']['steps'][0]['ko'])
        invalid=deepcopy(raw);invalid['reviewGuide']['steps'][0]['ko']='99초에 시작하세요.'
        with self.assertRaises(ValueError):validate_plan(invalid,context)
        invalid=deepcopy(raw);invalid['videoRefs']=['invented']
        with self.assertRaises(ValueError):validate_plan(invalid,context)

    def test_question_about_active_practice_does_not_create_a_second_exercise(self):
        from agent.coaching import new_document,respond
        from agent.report_agent import generate_report
        from server.tests.test_feedback_selection import measured_request
        req=measured_request(2);report=generate_report(req,model_version=req.modelVersion,agent_mode=True)
        doc=new_document(req,report,req.modelVersion)
        doc,_=respond(doc,CoachRequest(sessionId=req.sessionId,action="create_practice",findingId="v2_jitter",practiceStrategyId="two_versions"))
        active=doc['state']['activePracticeId']
        def answer(context):
            self.assertIn('practice.task',context['facts'])
            return {'action':'ask','findingId':'v2_jitter','evidenceIds':[],
                    'message':{'ko':'같은 문장을 두 방식으로 말한 뒤, 어느 쪽에서 뜻이 더 잘 전달되는지 골라보세요.','en':'Say the same sentence in both ways, then choose which better conveys your intent.'}}
        for question in ['이 연습에서 무엇을 비교하면 돼?','What should I compare in this practice?']:
            updated,response=respond_with_ai(doc,CoachRequest(sessionId=req.sessionId,action='ask',message=question),generate=answer,verify=lambda _: {'supported':True})
            self.assertEqual(len(updated['practices']),1)
            self.assertEqual(updated['state']['activePracticeId'],active)
            self.assertEqual(updated['state']['stage'],'practice_created')
            self.assertEqual(response['generation']['source'],'ai')
            actions=[choice['action'] for component in response['components'] if component['type']=='action_choices' for choice in component['choices']]
            self.assertIn('start_recording',actions)

    def test_provider_aliases_never_send_saved_identity_and_restore_references(self):
        from agent.coach_ai import anonymize_provider_context
        identity='a9622c30-5b4f-4b65-884e-487822b61974'
        context={'request':{'sessionId':identity},'state':{'sessionId':identity},'sessionSummaries':{'current':{'recordedAt':'private date','scene':'private filename'}},'responseSchema':{'const':identity}}
        safe,restore=anonymize_provider_context(context)
        self.assertNotIn(identity,str(safe));self.assertNotIn('private',str(safe))
        self.assertEqual(safe['request']['sessionId'],safe['state']['sessionId'])
        self.assertEqual(restore({'id':safe['request']['sessionId']})['id'],identity)
        self.assertEqual(context['request']['sessionId'],identity)


if __name__ == "__main__":
    unittest.main()
