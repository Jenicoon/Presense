"use client";
import { useEffect, useState } from "react";
import type { CoachActionContext, CoachComponent, DeliveryReview } from "@/lib/coaching";

type ReviewCard = Extract<CoachComponent, {type: "practice_review"}>;
type Draft = {sameContent: string; sameEnvironment: string; answers: Record<string, string>};
const blank = (): Draft => ({sameContent: "", sameEnvironment: "", answers: {}});
const conditions = ["same", "changed", "unknown"];
const answers = ["yes", "partly", "no", "unavailable"];

export function PracticeReviewForm({card, ko, busy, onSubmit}: {
  card: ReviewCard; ko: boolean; busy: boolean; onSubmit: (context: CoachActionContext) => void;
}) {
  const key = `presense-practice-review:${card.practiceId}:${card.attemptSessionId}`;
  const [draft, setDraft] = useState<Draft>(blank);
  const [loadedKey, setLoadedKey] = useState("");
  const loaded = loadedKey === key;
  useEffect(() => {
    setLoadedKey("");
    try {
      const saved = JSON.parse(window.localStorage.getItem(key) ?? "null");
      setDraft(saved && typeof saved.answers === "object" && saved.answers ? saved : card.review ? {sameContent: card.review.sameContent, sameEnvironment: card.review.sameEnvironment, answers: card.review.answers} : blank());
    } catch { setDraft(blank()); }
    setLoadedKey(key);
  }, [key]);
  useEffect(() => {
    if (loaded) { try { window.localStorage.setItem(key, JSON.stringify(draft)); } catch {} }
  }, [draft, loaded, key]);
  const complete = conditions.includes(draft.sameContent) && conditions.includes(draft.sameEnvironment) &&
    card.checks.every(check => answers.includes(draft.answers[check.id]));
  return <form className="coach-card coach-review-form" aria-label={ko ? "연습 결과 확인" : "Review practice results"} onSubmit={event => {
    event.preventDefault();
    if (busy || !complete || !loaded) return;
    onSubmit({deliveryReview: {
      practiceId: card.practiceId, attemptSessionId: card.attemptSessionId,
      sameContent: draft.sameContent, sameEnvironment: draft.sameEnvironment,
      answers: Object.fromEntries(card.checks.map(check => [check.id, draft.answers[check.id]])),
    } as DeliveryReview});
  }}>
    <strong>{ko ? "두 영상을 보고 연습 결과를 확인하세요" : "Watch both takes and check your practice"}</strong>
    <p>{ko ? "연습 전에 정한 두 행동을 하나씩 확인해요. 직접 확인한 답으로 결과를 기록합니다." : "Check each action you chose before recording. The result records your own review."}</p>
    <fieldset disabled={busy || !loaded}>
      <legend>{ko ? "비교 조건" : "Comparison conditions"}</legend>
      {([['sameContent', ko ? '다시 말한 내용' : 'Content you repeated'], ['sameEnvironment', ko ? '카메라·마이크 환경' : 'Camera and microphone setup']] as const).map(([field, label]) => <label key={field}>{label}<select aria-label={label} required value={draft[field]} onChange={event => setDraft(value => ({...value, [field]: event.target.value}))}>
        <option value="">{ko ? "선택해 주세요" : "Choose an answer"}</option>
        <option value="same">{ko ? "같아요" : "The same"}</option><option value="changed">{ko ? "달라졌어요" : "Changed"}</option><option value="unknown">{ko ? "확인하기 어려워요" : "Unable to confirm"}</option>
      </select></label>)}
    </fieldset>
    <fieldset disabled={busy || !loaded}>
      <legend>{ko ? "연습에서 정한 행동" : "Your chosen practice actions"}</legend>
      {card.checks.map(check => <label key={check.id}>{check.label}<select aria-label={check.label} required value={draft.answers[check.id] ?? ""} onChange={event => setDraft(value => ({...value, answers: {...value.answers, [check.id]: event.target.value}}))}>
        <option value="">{ko ? "선택해 주세요" : "Choose an answer"}</option>
        <option value="yes">{ko ? "했어요" : "Yes"}</option><option value="partly">{ko ? "일부만 했어요" : "Partly"}</option><option value="no">{ko ? "아직 못 했어요" : "Not yet"}</option><option value="unavailable">{ko ? "확인하기 어려워요" : "Unable to assess"}</option>
      </select></label>)}
    </fieldset>
    <p className="coach-review-note">{ko ? "모두 실행했으면 달성, 일부 실행했으면 부분 달성으로 기록해요. 조건이 달라졌거나 확인이 어려우면 평가를 보류해요." : "All actions completed: achieved. Some completed: partly achieved. Changed or unconfirmed conditions: assessment withheld."}</p>
    <button type="submit" className="btn btn-primary" disabled={busy || !loaded || !complete}>{ko ? "확인 결과 저장" : "Save my review"}</button>
  </form>;
}
