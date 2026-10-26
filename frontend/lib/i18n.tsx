"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "ko" | "en";

const STORAGE_KEY = "presense-lang";
const DEFAULT_LANG: Lang = "en";

// Flat key → { ko, en }. Use t("key") to read the current language.
const dict: Record<string, { ko: string; en: string }> = {
  // ── App shell ──
  "brand.tagline": { ko: "발표 AI", en: "Presentation AI" },
  "nav.dashboard": { ko: "대시보드", en: "Dashboard" },
  "nav.history": { ko: "기록", en: "History" },
  "nav.practice": { ko: "연습", en: "Practice" },
  "nav.settings": { ko: "설정", en: "Settings" },
  "agent.title": { ko: "AI ChatBot", en: "AI ChatBot" },
  "agent.sidebarHint": { ko: "최근 세션과 대화", en: "Talk about your sessions" },
  "agent.subtitle": { ko: "언제든 연습 기록을 함께 살펴보세요", en: "Discuss your practice anytime" },
  "agent.open": { ko: "AI ChatBot 열기", en: "Open AI ChatBot" },
  "agent.close": { ko: "AI ChatBot 닫기", en: "Close AI ChatBot" },
  "agent.expand": { ko: "채팅창 크게 보기", en: "Expand chat" },
  "agent.shrink": { ko: "채팅창 작게 보기", en: "Shrink chat" },
  "agent.contextTitle": { ko: "연결된 세션", en: "Session context" },
  "agent.currentSession": { ko: "방금 끝난 세션의 분석 결과도 포함됩니다.", en: "The session you just finished is included." },
  "agent.refresh": { ko: "최근 세션 새로고침", en: "Refresh recent sessions" },
  "agent.loadingSessions": { ko: "최근 세션을 불러오는 중…", en: "Loading recent sessions…" },
  "agent.sessionsError": { ko: "세션 기록을 불러오지 못했습니다. 새로고침해 주세요.", en: "Could not load sessions. Please refresh." },
  "agent.noSessions": { ko: "저장된 세션이 없어도 연습에 관해 질문할 수 있어요.", en: "You can ask practice questions before saving a session." },
  "agent.allRecent": { ko: "최근 세션", en: "Recent sessions" },
  "agent.welcome": { ko: "연습 방법을 물어보거나 최근 세션을 비교해 보세요.", en: "Ask for practice advice or compare recent sessions." },
  "agent.thinking": { ko: "답변을 작성하는 중…", en: "Writing a reply…" },
  "agent.placeholder": { ko: "최근 세션에서 가장 개선할 점은?", en: "What should I improve from my recent sessions?" },
  "agent.send": { ko: "질문 보내기", en: "Send question" },
  "agent.signIn": { ko: "로그인 후 AI ChatBot을 사용할 수 있습니다.", en: "Sign in to use the AI ChatBot." },
  "agent.requestFailed": { ko: "AI ChatBot에 연결하지 못했습니다. 다시 시도해 주세요.", en: "Could not reach the AI ChatBot. Please try again." },
  "agent.emptyReply": { ko: "AI ChatBot에서 빈 답변을 받았습니다.", en: "The AI ChatBot returned an empty reply." },
  "agent.privacy": { ko: "선택한 세션의 저장된 분석 자료를 바탕으로 답변합니다.", en: "Answers use the selected session’s saved analysis data." },
  "agent.reportHint": { ko: "이번 세션과 최근 기록을 함께 살펴보세요.", en: "Discuss this session alongside your recent records." },
  "agent.openForReport": { ko: "이번 세션으로 AI ChatBot 열기", en: "Open AI ChatBot with this session" },
  "cta.startPractice": { ko: "연습 시작", en: "Start Practice" },
  "header.search": { ko: "세션 검색...", en: "Search sessions..." },
  "menu.settings": { ko: "설정", en: "Settings" },
  "menu.signOut": { ko: "로그아웃", en: "Sign out" },
  "menu.login": { ko: "로그인", en: "Log in" },
  "common.loadingWorkspace": { ko: "작업공간을 불러오는 중...", en: "Loading your workspace..." },
  "lang.toggle": { ko: "언어 전환", en: "Toggle language" },

  // ── Auth ──
  "auth.headline": { ko: "더 똑똑하게 연습하고,\n더 잘 발표하세요.", en: "Practice smarter,\npresent better." },
  "auth.desc": {
    ko: "웹캠과 마이크만으로 발표의 모델 신호를 분석하는 플랫폼",
    en: "Presentation signal analysis platform\nfrom your webcam and microphone",
  },
  "auth.feature1": { ko: "실시간 카메라 + 마이크 분석", en: "Live camera + microphone analysis" },
  "auth.feature2": { ko: "세션마다 AI 발표 신호 분석", en: "AI presentation signal analysis after each session" },
  "auth.feature3": { ko: "세션 기록 및 진행 상황 추적", en: "Session history and progress tracking" },
  "auth.welcomeBack": { ko: "다시 오신 걸 환영합니다", en: "Welcome back" },
  "auth.createAccount": { ko: "계정 만들기", en: "Create account" },
  "auth.signInSub": { ko: "PreSense 계정으로 로그인하세요.", en: "Sign in to your PreSense account." },
  "auth.signUpSub": { ko: "발표 연습 여정을 시작하세요.", en: "Start your presentation practice journey." },
  "auth.login": { ko: "로그인", en: "Login" },
  "auth.signUp": { ko: "회원가입", en: "Sign Up" },
  "auth.forgotIntro": { ko: "계정 이메일을 입력하면 비밀번호 복구 링크를 보내드립니다.", en: "Enter your account email and we will send a password recovery link." },
  "auth.name": { ko: "이름", en: "Name" },
  "auth.namePlaceholder": { ko: "성함을 입력하세요", en: "Your full name" },
  "auth.email": { ko: "이메일", en: "Email" },
  "auth.password": { ko: "비밀번호", en: "Password" },
  "auth.passwordPlaceholder": { ko: "비밀번호 입력", en: "Enter password" },
  "auth.forgotPassword": { ko: "비밀번호를 잊으셨나요?", en: "Forgot password?" },
  "auth.sendRecovery": { ko: "복구 이메일 보내기", en: "Send Recovery Email" },
  "auth.sending": { ko: "보내는 중…", en: "Sending…" },
  "auth.backToLogin": { ko: "← 로그인으로 돌아가기", en: "← Back to login" },
  "auth.notConfigured": { ko: "Supabase 미설정 — 인증이 비활성화되었습니다.", en: "Supabase not configured — auth is disabled." },
  "auth.pleaseWait": { ko: "잠시만 기다려 주세요...", en: "Please wait..." },
  "auth.enterDashboard": { ko: "로그인", en: "Enter" },
  "auth.createAccountBtn": { ko: "계정 생성", en: "Create Account" },
  "auth.recoverySent": { ko: "복구 이메일을 보냈습니다. 받은편지함에서 링크를 확인하세요.", en: "Recovery email sent. Check your inbox and click the link." },
  "auth.recoveryFailed": { ko: "복구 이메일 전송에 실패했습니다.", en: "Failed to send recovery email." },
  "auth.created": { ko: "계정이 생성되었습니다. 로그인 전 이메일에서 확인해 주세요.", en: "Account created. Check your email to confirm before logging in." },
  "auth.failed": { ko: "인증에 실패했습니다.", en: "Authentication failed." },

  // ── Settings ──
  "settings.title": { ko: "설정", en: "Settings" },
  "settings.subtitle": {
    ko: "연습 환경, 개인정보, AI 코칭 옵션을 관리하세요.",
    en: "Manage your practice preferences, privacy, and AI coaching options.",
  },
  "settings.savedBrowserOnly": { ko: "이 브라우저에만 저장되었습니다.", en: "Saved in this browser only." },
  "settings.savedAccount": { ko: "계정에 저장되었습니다.", en: "Saved to your account." },
  "settings.failedLoad": { ko: "설정을 불러오지 못했습니다.", en: "Failed to load settings." },
  "settings.failedSave": { ko: "설정을 저장하지 못했습니다.", en: "Failed to save settings." },
  "settings.clickToToggle": { ko: "클릭하여 전환", en: "Click to toggle" },
  "settings.language": { ko: "언어", en: "Language" },
  "settings.languageDesc": { ko: "인터페이스 표시 언어", en: "Interface display language" },
  "toggle.enabled": { ko: "켜짐", en: "Enabled" },
  "toggle.disabled": { ko: "꺼짐", en: "Disabled" },
  "toggle.on": { ko: "켜짐", en: "On" },
  "toggle.off": { ko: "꺼짐", en: "Off" },

  // Settings — primary toggles (by id)
  "set.camera-preview": { ko: "기본으로 실시간 카메라 미리보기", en: "Default to live camera preview" },
  "set.microphone-active-only": { ko: "활성 세션 중에만 캡처", en: "Only capture during active sessions" },
  "set.session-summary-notice": { ko: "세션마다 요약 표시", en: "Show summary after each session" },
  // Settings — section titles
  "set.section.Session Preferences": { ko: "세션 환경설정", en: "Session Preferences" },
  "set.section.Privacy Controls": { ko: "개인정보 설정", en: "Privacy Controls" },
  "set.section.AI ChatBot Preferences": { ko: "AI ChatBot 설정", en: "AI ChatBot Preferences" },
  // Settings — section items (by id)
  "set.default-camera-view": { ko: "연습 시작 시 기본 카메라 화면", en: "Default camera view on practice start" },
  "set.mute-live-feedback": { ko: "세션 종료 전까지 실시간 피드백 음소거", en: "Mute live feedback until session ends" },
  "set.auto-ai-summary": { ko: "세션 후 AI 코칭 요약 자동 생성", en: "Generate post-session AI coaching summary automatically" },
  "set.store-summaries-only": { ko: "세션 요약만 저장", en: "Store session summaries only" },
  "set.disable-frame-storage": { ko: "원본 카메라 프레임 저장 안 함", en: "Do not save raw camera preview frames" },
  "set.mic-active-practice-only": { ko: "활성 연습 중에만 마이크 접근 허용", en: "Allow microphone access only during active practice" },
  "set.concise-coaching-tone": { ko: "간결한 코칭 톤 사용", en: "Use concise coaching tone" },
  "set.prioritize-presentation-advice": { ko: "발표 관련 조언 우선", en: "Prioritize presentation-specific advice" },
  "set.future-api-key-connection": { ko: "향후 API 키 연결 준비", en: "Prepare for future API key connection" },

  // ── Dashboard ──
  "dash.title": { ko: "시스템 개요", en: "System Overview" },
  "dash.subtitle": { ko: "발표 연습으로부터의 실시간 인사이트.", en: "Real-time intelligence from your presentation practice." },
  "kpi.totalSessions": { ko: "전체 세션", en: "Total Sessions" },
  "kpi.totalSessions.synced": { ko: "계정에 저장됨", en: "Saved to your account" },
  "kpi.totalSessions.local": { ko: "Supabase 연결 시 동기화", en: "Add Supabase to sync" },
  "kpi.latestAvgStress": { ko: "최근 평균 모델 점수", en: "Latest mean model score" },
  "kpi.scoreOutOf": { ko: "1.00 만점 점수", en: "Score out of 1.00" },
  "kpi.currentFocus": { ko: "현재 집중 영역", en: "Current Focus Area" },
  "kpi.currentFocusSub": { ko: "가장 주의가 필요한 맥락", en: "Context needing the most attention" },
  "kpi.latestDiagnosis": { ko: "최근 진단", en: "Latest Diagnosis" },
  "kpi.latestDiagnosisSub": { ko: "AI 코칭 요약", en: "AI coaching summary" },
  "badge.synced": { ko: "동기화됨", en: "Synced" },
  "badge.local": { ko: "로컬", en: "Local" },
  "badge.latest": { ko: "최근", en: "Latest" },
  "panel.stressTrend": { ko: "시간별 모델 점수", en: "Model scores over time" },
  "panel.stressTrendSub": { ko: "세션별 평균 모델 점수", en: "Mean model score per session" },
  "legend.stressScore": { ko: "모델 스트레스 신호", en: "Model stress signal" },
  "chart.oldest": { ko: "가장 오래됨", en: "Oldest" },
  "chart.latest": { ko: "최근", en: "Latest" },
  "panel.sessionsByScene": { ko: "장면별 세션", en: "Sessions by Scene" },
  "panel.sessionsBySceneSub": { ko: "연습 모드 분포", en: "Practice mode breakdown" },
  "state.loadingSessions": { ko: "세션 불러오는 중...", en: "Loading sessions..." },
  "state.noSessionsTrend": { ko: "아직 세션이 없습니다 — 연습을 끝내면 추이가 표시됩니다.", en: "No sessions yet — finish a practice run to see your trend." },
  "state.noSessionsScene": { ko: "아직 세션이 없습니다 — 연습이 장면별로 여기 모입니다.", en: "No sessions yet — practice runs will be grouped by scene here." },
  "unit.session": { ko: "세션", en: "session" },
  "unit.sessions": { ko: "세션", en: "sessions" },
  "panel.recentSessions": { ko: "최근 세션", en: "Recent Sessions" },
  "panel.recentSessionsSub": { ko: "세션 기록 및 결과", en: "Session history & results" },
  "table.date": { ko: "날짜", en: "Date" },
  "table.title": { ko: "제목", en: "Title" },
  "table.duration": { ko: "시간", en: "Duration" },
  "table.avgStress": { ko: "평균 모델 점수", en: "Mean model score" },
  "table.result": { ko: "결과", en: "Result" },
  "table.action": { ko: "동작", en: "Action" },
  "table.review": { ko: "리뷰", en: "Review" },
  "table.loading": { ko: "불러오는 중...", en: "Loading..." },
  "table.noSessions": { ko: "아직 세션이 없습니다. 연습을 끝내면 여기 표시됩니다.", en: "No sessions yet. Finish a practice run to see it here." },

  // ── Review modal ──
  "modal.sessionReview": { ko: "세션 리뷰", en: "Session Review" },
  "modal.avgStressScore": { ko: "평균 모델 점수", en: "Mean model score" },
  "modal.outOfHigh": { ko: "0–1 분석 눈금 · 높은 모델 점수", en: "0\u20131 analysis scale \u00b7 higher model score" },
  "modal.outOfModerate": { ko: "0–1 분석 눈금 · 중간 모델 점수", en: "0\u20131 analysis scale \u00b7 middle model score" },
  "modal.outOfLow": { ko: "0–1 분석 눈금 · 낮은 모델 점수", en: "0\u20131 analysis scale \u00b7 lower model score" },
  "modal.stressPhaseBreakdown": { ko: "표시 구간별 모델 점수", en: "Model scores by display interval" },
  "modal.aiDiagnosis": { ko: "AI 진단", en: "AI Diagnosis" },
  "modal.overallJudgment": { ko: "종합 판단", en: "Overall Judgment" },
  "modal.viewDetails": { ko: "상세 보기", en: "View details" },
  "modal.peakPressureAnalysis": { ko: "최고 압박 분석", en: "Peak Pressure Analysis" },
  "modal.noDiagnosis": { ko: "기록된 진단이 없습니다.", en: "No diagnosis recorded." },
  "modal.recommendedNextStep": { ko: "추천 다음 단계", en: "Recommended Next Step" },
  "modal.coachingInsight": { ko: "코칭 인사이트", en: "Coaching Insight" },
  "modal.coach.high": {
    ko: "높은 스트레스 감지 — 주요 포인트 사이에서 속도를 늦추는 데 집중하세요. 핵심 용어 뒤에 1~2초의 의도적인 쉼을 넣어 청중이 이해하고 본인도 호흡을 가다듬을 시간을 주세요.",
    en: "High stress detected — focus on slowing down between major points. Insert deliberate pauses (1–2 seconds) after each key term to allow the audience to absorb information and give yourself time to reset.",
  },
  "modal.coach.moderate": {
    ko: "보통 스트레스 감지 — 기본은 괜찮지만 눈에 띄는 압박 구간이 있었습니다. 긴장이 쌓이기 쉬운 중반 핵심 내용에서 일정한 속도를 유지하는 데 집중하세요.",
    en: "Moderate stress detected — your baseline is acceptable but there were noticeable pressure spikes. Work on keeping a consistent pace in the mid-session core content where tension tends to build.",
  },
  "modal.coach.low": {
    ko: "낮은 스트레스 감지 — 전달이 안정적이었습니다. 더 발전하려면 표현 변화에 집중하세요: 핵심 용어를 의도적으로 강조하면 불안을 키우지 않고도 발표가 더 생동감 있어집니다.",
    en: "Low stress detected — delivery was stable. To improve further, focus on expressive variation: deliberate emphasis on key terms will make your presentation more engaging without raising anxiety.",
  },
  "sev.high": { ko: "높음", en: "High" },
  "sev.moderate": { ko: "보통", en: "Moderate" },
  "sev.low": { ko: "낮음", en: "Low" },
  "diag.latestSessionResult": { ko: "최근 세션 결과", en: "Latest session result" },
  "diag.averageStress": { ko: "평균 모델 점수", en: "Mean model score" },
  "diag.nextCoachingFocus": { ko: "다음 코칭 집중 영역", en: "Next coaching focus" },
  "diag.generatedFromSession": { ko: "AI 진단", en: "AI diagnosis" },
  "diag.noDeck": { ko: "사용한 자료 없음", en: "No deck used" },
  "diag.phase.open": { ko: "도입", en: "Open" },
  "diag.phase.build": { ko: "전개", en: "Build" },
  "diag.phase.core": { ko: "핵심", en: "Core" },
  "diag.phase.close": { ko: "마무리", en: "Close" },
  "diag.peakPressure": { ko: "최고 압박은 {phase} 단계에서 {value}%까지 높아졌습니다. 자료: {deck}.", en: "Peak pressure reached {value}% around the {phase} phase. Deck: {deck}." },
  "diag.noticeablePressure": { ko: "{phase} 구간에서 눈에 띄는 압박", en: "Noticeable {phase}-section pressure" },
  "diag.stableDelivery": { ko: "전반적으로 안정적인 발표", en: "Mostly stable delivery" },
  "diag.nextAction": { ko: "주요 설명 구간 사이의 전환을 더 천천히 연습하고, 핵심 용어마다 짧게 멈춰 보세요.", en: "Practice slower transitions between your main explanation blocks and leave a short pause after each key term." },

  // ── Practice ──
  "practice.title": { ko: "연습 세션", en: "Practice Session" },
  "practice.subtitle": {
    ko: "슬라이드, 청중 압박, 조용한 세션 후 분석으로 연습하세요.",
    en: "Rehearse with slides, audience pressure, and quiet post-session analysis.",
  },
  "btn.endSession": { ko: "세션 종료", en: "End Session" },
  "btn.startSession": { ko: "세션 시작", en: "Start Session" },
  "setup.rehearsalDeck": { ko: "리허설 자료", en: "Rehearsal Deck" },
  "setup.noDeck": { ko: "선택된 자료 없음", en: "No deck selected" },
  "setup.ready": { ko: "무대 미리보기 준비 완료.", en: "Ready for stage preview." },
  "setup.needsPdf": { ko: "미리보기는 PDF 변환이 필요합니다.", en: "Preview requires PDF conversion." },
  "setup.uploadOrSample": { ko: "PDF를 업로드하거나 샘플 프레젠테이션을 사용하세요.", en: "Upload a PDF or use the sample presentation." },
  "btn.uploadDeck": { ko: "자료 업로드", en: "Upload Deck" },
  "btn.useSample": { ko: "샘플 사용", en: "Use Sample" },
  "mode.label": { ko: "피드백 표시", en: "Feedback display" },
  "mode.silent": { ko: "숨김", en: "Hidden" },
  "mode.gentle": { ko: "항상 표시", en: "Always" },
  "mode.active": { ko: "주의 시 표시", en: "On alert" },
  "signal.sessionMode": { ko: "세션 모드", en: "Session Mode" },
  "signal.elapsed": { ko: "경과 시간", en: "Elapsed Time" },
  "signal.mic": { ko: "마이크 활동", en: "Mic Activity" },
  "signal.camera": { ko: "카메라", en: "Camera" },
  "signal.liveStress": { ko: "모델 스트레스 신호", en: "Model stress signal" },
  "signal.feedbackState": { ko: "피드백 상태", en: "Feedback State" },
  "val.live": { ko: "라이브", en: "LIVE" },
  "val.done": { ko: "완료", en: "DONE" },
  "val.ready": { ko: "준비", en: "READY" },
  "val.on": { ko: "켜짐", en: "ON" },
  "val.preview": { ko: "미리보기", en: "PREVIEW" },
  "val.stby": { ko: "대기", en: "STBY" },
  "val.hidden": { ko: "숨김", en: "HIDDEN" },
  "state.live": { ko: "라이브 연습", en: "Live practice" },
  "state.ended": { ko: "세션 완료", en: "Session completed" },
  "state.starting": { ko: "시작 중", en: "Starting" },
  "state.error": { ko: "권한 필요", en: "Permission needed" },
  "state.ready": { ko: "시작 준비됨", en: "Ready to start" },

  // FeedbackEngine messages
  "fb.idle": { ko: "자세한 피드백은 세션 종료 후 제공됩니다.", en: "Detailed feedback appears after the session." },
  "fb.learning": { ko: "분석 결과를 수집하는 중…", en: "Collecting analysis results\u2026" },
  "fb.stable": { ko: "모델 점수가 낮게 나타났습니다", en: "The model score is lower" },
  "fb.steady": { ko: "관측된 신호는 세션 보고서에서 확인하세요.", en: "Review observed signals in the session report." },
  "fb.mid": { ko: "모델 점수 변화가 관측되었습니다", en: "A model-score change was observed" },
  "fb.high": { ko: "이 구간은 종료 후 영상에서 확인하세요", en: "Review this interval in the recording after the session" },
  "fb.activeQuiet": { ko: "모델 점수의 변화를 관찰하고 있습니다.", en: "Observing changes in the model score." },

  // Signal note
  "note.simulated": {
    ko: "데모 신호 — Student 모델 추론 백엔드가 연결되기 전까지 stress와 confidence는 시뮬레이션입니다.",
    en: "Demo signal — stress & confidence are simulated until the Student-model inference backend is connected.",
  },
  "note.liveError": {
    ko: "분석 요청에 실패했거나 응답 시간이 초과됐습니다. 서버 실행 상태와 주소를 확인해 주세요.",
    en: "Analysis failed or timed out. Check the server status and URL.",
  },
  "note.liveOk": {
    ko: "모델 서버에 연결됨 · 실제 모델 분석 결과를 수신하고 있습니다.",
    en: "Connected to the model server · Receiving model analysis results.",
  },
  "note.liveVerified": {
    ko: "모델 서버 연결 확인 완료 · 마지막 분석 요청 기준",
    en: "Model connection verified on the last analysis request.",
  },
  "note.liveIdle": { ko: "연습을 시작하면 영상·음성을 수집해 분석합니다.", en: "Start practice to collect video and audio for analysis." },
  "note.preparation": { ko: "카메라·마이크로 분석 준비 데이터를 미리 수집합니다. 시작 전에는 브라우저에만 임시 보관하며, 연습을 시작하면 분석 서버로 전송합니다.", en: "We collect camera and microphone data for preparation. It stays temporarily in your browser until practice starts, when it is sent for analysis." },
  "note.preparationFrames": { ko: "영상 준비", en: "Video preparation" },
  "note.preparationAudioOn": { ko: "마이크 수집 중", en: "Collecting audio" },
  "note.preparationAudioOff": { ko: "마이크 준비 대기", en: "Audio preparation pending" },
  "note.prepareButton": { ko: "카메라·마이크 준비", en: "Prepare camera and microphone" },
  "note.liveCollecting": { ko: "첫 분석을 위한 영상·음성 수집 중 · 약 10초 후 분석 요청", en: "Collecting video and audio · First analysis requested after about 10 seconds" },
  "note.liveAnalyzing": { ko: "영상·음성 분석 중… 첫 결과는 시간이 걸릴 수 있습니다.", en: "Analyzing video and audio… The first result may take a while." },
  "note.liveCamera": { ko: "카메라 영상을 기다리는 중입니다. 카메라 권한과 미리보기를 확인해 주세요.", en: "Waiting for video. Check camera permission and preview." },
  "note.liveAudio": { ko: "마이크 데이터를 기다리는 중입니다. 마이크 권한을 확인해 주세요.", en: "Waiting for audio. Check microphone permission." },

  // Slides / deck
  "slide.hint": { ko: "← / → 키로 슬라이드 이동", en: "Use ← / → keys to move between slides" },
  "deck.addFile": { ko: "발표 파일을 추가하세요", en: "Add your presentation file" },
  "deck.addFileDesc": { ko: "PDF는 즉시 동작하거나, 샘플 프레젠테이션 덱을 사용하세요.", en: "PDF works instantly, or use the sample presentation deck." },
  "deck.pptDesc": { ko: "PowerPoint 미리보기는 PDF 변환이 필요합니다. 라이브 리허설 화면을 위해 PDF로 내보내세요.", en: "PowerPoint preview requires PDF conversion. Export this deck as PDF for the live rehearsal view." },

  // Report
  "report.timeline": { ko: "세션 모델 신호 타임라인", en: "Session model signal timeline" },
  "report.timelineSub": { ko: "실제 관측 시간별 분석 점수", en: "Analysis scores at observed times" },
  "report.diagnosis": { ko: "진단", en: "Diagnosis" },
  "report.diagnosisSub": { ko: "AI 분석 결과", en: "AI analysis result" },
  "report.overallJudgment": { ko: "종합 판단", en: "Overall Judgment" },
  "report.peakPoint": { ko: "다시 볼 관측 구간", en: "Observed interval to review" },
  "report.summary": { ko: "세션 요약", en: "Session Summary" },
  "report.summarySub": { ko: "다음 리허설에서 개선할 점", en: "What to improve next rehearsal" },
  "report.overallAvg": { ko: "세션 평균 모델 점수", en: "Session mean model score" },
  "report.overallAvgDesc": { ko: "품질 확인을 통과한 관측 시간의 평균입니다.", en: "Mean over observed time passing quality checks." },
  "report.peakStress": { ko: "최고 모델 점수와 시간", en: "Peak model score and time" },
  "report.peakStressDesc": { ko: "실제 분석창 중 가장 높은 모델 점수입니다.", en: "Highest model score from an actual analysis window." },
  "report.mostStressfulPhase": { ko: "평균 모델 점수가 높은 표시 구간", en: "Display interval with highest mean model score" },
  "report.mostStressfulPhaseDesc": { ko: "발표 구조 인식이 아닌 시간 분할입니다.", en: "A division of time, not recognized presentation structure." },
  "report.nextStep": { ko: "추천 다음 단계", en: "Recommended Next Step" },
  "report.nextStepDesc": { ko: "다음 리허설의 집중 영역.", en: "Focus area for your next rehearsal." },
  "report.confidence": { ko: "Confidence", en: "Confidence" },
  "report.deck": { ko: "자료", en: "Deck" },
  "report.scene": { ko: "장면", en: "Scene" },
  "report.aiAgent": { ko: "AI ChatBot", en: "AI ChatBot" },
  "report.aiAgentSub": { ko: "후속 질문하기", en: "Ask follow-up questions" },
  "report.chatPlaceholder": { ko: "세션 결과에 대해 물어보세요...", en: "Ask about your session result..." },
  "report.ask": { ko: "질문", en: "Ask" },

  // Report dynamic text
  "phase.suffix": { ko: "단계", en: "phase" },
  "report.binLabel": { ko: "구간", en: "bin" },
  "report.stateStable": { ko: "관측 구간에서 모델 점수가 비슷했습니다", en: "Observed model scores were similar" },
  "report.nextActionText": { ko: "실제 구간별 분석 결과를 확인한 뒤 다음 연습을 선택하세요.", en: "Review the observed intervals, then choose your next practice." },
  "report.chatIntro": {
    ko: "세션이 끝나면 성과를 요약하고 후속 질문에 답해 드릴게요.",
    en: "After the session ends, I will summarize your performance and answer follow-up questions here.",
  },
  "report.chatWaiting": {
    ko: "세션이 끝나길 기다리는 중입니다. 종료하면 결과 해석을 도와드릴게요.",
    en: "Waiting for the session to finish. I will help interpret the results when you end it.",
  },
  "report.chatSummaryPrefix": { ko: "세션 요약이 준비됐어요. 가장 개선할 부분: ", en: "Session summary ready. Biggest improvement area: " },

  // AI agent replies
  "agent.stressPre": { ko: "모델 점수가 높았던 구간은 ", en: "The interval with the higher model score was " },
  "agent.stressPost": { ko: "입니다. 영상에서 실제 발화와 표정을 확인하세요.", en: ". Review the recorded speech and expression." },
  "agent.stressFallback": { ko: "분석 자료 없음", en: "No analysis data" },
  "agent.calm": { ko: "저장된 분석 결과와 영상을 함께 확인해 주세요.", en: "Review saved analysis alongside the recording." },
  "agent.default": { ko: "관측 구간과 측정값을 확인하고 연습 목표를 선택하세요.", en: "Review observed intervals and measurements, then choose a practice goal." },

  // Agent starter pills
  "starter.0": { ko: "모델 점수가 가장 두드러진 구간은?", en: "Where was the model score most prominent?" },
  "starter.1": { ko: "다음 리허설 전에 무엇을 개선해야 할까?", en: "What should I improve before the next rehearsal?" },
  "starter.2": { ko: "해당 구간에서 어떤 측정값이 관측됐어?", en: "What measurements were observed in that interval?" },

  // Post-session highlights
  "highlight.0.title": { ko: "관측 구간 확인", en: "Review observed intervals" },
  "highlight.0.detail": { ko: "분석된 구간과 빈 구간을 타임라인에서 확인하세요.", en: "Review observed and missing intervals on the timeline." },
  "highlight.1.title": { ko: "영상과 함께 확인", en: "Review with the recording" },
  "highlight.1.detail": { ko: "음성·영상 측정값은 실제 전달 맥락과 함께 확인하세요.", en: "Review audio and video measurements in the context of delivery." },
  "highlight.2.title": { ko: "다음 목표 선택", en: "Choose the next goal" },
  "highlight.2.detail": { ko: "근거가 확인된 목표 하나를 선택해 같은 내용으로 다시 연습하세요.", en: "Choose one supported goal and repeat the same content." },

  // Session naming
  "save.title": { ko: "세션 저장", en: "Save Session" },
  "save.subtitle": { ko: "이 연습 세션의 이름을 정하세요", en: "Name this practice session" },
  "save.namePlaceholder": { ko: "세션 이름 입력...", en: "Enter a session name..." },
  "save.button": { ko: "세션 저장", en: "Save Session" },
  "save.saved": { ko: "저장됨", en: "Saved" },
  "save.defaultSuffix": { ko: "연습", en: "Practice" },

  // Errors / status
  "err.permission": { ko: "카메라 또는 마이크 권한이 거부되었습니다.", en: "Camera or microphone permission was denied." },
  "err.cameraPreview": { ko: "카메라 권한이 거부되었습니다. 시작 전에 본인 모습을 미리 보려면 접근을 허용하세요.", en: "Camera permission was denied. Allow access to preview yourself before starting." },
  "status.localOnly": { ko: "Supabase 미연결. 세션이 로컬에만 저장되었습니다.", en: "Supabase not connected. Session saved locally only." },
  "status.saved": { ko: "세션이 계정에 저장되었습니다.", en: "Session saved to your account." },
  "status.saveFailed": { ko: "세션 저장에 실패했습니다.", en: "Failed to save session." },

  // Scenes (by id)
  "scene.camera.label": { ko: "실시간 카메라", en: "Live Camera" },
  "scene.camera.desc": { ko: "연습 중 실제 웹캠 미리보기를 사용합니다.", en: "Use your real webcam preview during practice." },
  "scene.audience.label": { ko: "강의실 청중", en: "Classroom Audience" },
  "scene.audience.desc": { ko: "강의실 청중이 당신을 바라보는 환경에서 연습합니다.", en: "Practice with a classroom audience looking toward you." },
  "scene.interview.label": { ko: "면접 패널", en: "Interview Panel" },
  "scene.interview.desc": { ko: "차분한 모의 면접 패널과 함께 연습합니다.", en: "Practice with a calm mock interview panel." },
  "scene.slides.label": { ko: "발표 슬라이드", en: "Presentation Slides" },
  "scene.slides.desc": { ko: "업로드한 자료를 메인 리허설 화면으로 표시합니다.", en: "Show your uploaded deck as the main rehearsal screen." },
  "scene.classroom-slides.label": { ko: "강의실 속 슬라이드", en: "Slides in Classroom" },
  "scene.classroom-slides.desc": { ko: "강의실 청중 앞에서 자료를 띄우고 연습합니다.", en: "Practice with your deck in front of a classroom audience." },
  "scene.audienceCaption": { ko: "강의실 청중 리허설", en: "Classroom audience rehearsal" },
  "interview.dr.name": { ko: "연구 책임자", en: "Research Lead" },
  "interview.dr.q": { ko: "모델 선택 이유를 1분 안에 설명해 주세요.", en: "Explain your model choice in one minute." },
  "interview.pm.name": { ko: "제품 리뷰어", en: "Product Reviewer" },
  "interview.pm.q": { ko: "실제 교실에서는 어떻게 동작하나요?", en: "How would this work in a real classroom?" },
  "interview.ai.name": { ko: "기술 패널", en: "Technical Panel" },
  "interview.ai.q": { ko: "카메라 각도가 바뀌면 어떻게 되나요?", en: "What happens when the camera angle changes?" },
};

type LangContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (key: string, fallback?: string) => string;
};

const LangContext = createContext<LangContextValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "ko" || stored === "en") setLangState(stored);
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    window.localStorage.setItem(STORAGE_KEY, l);
    document.documentElement.lang = l;
  }, []);

  const toggle = useCallback(() => setLang(lang === "ko" ? "en" : "ko"), [lang, setLang]);

  const t = useCallback(
    (key: string, fallback?: string) => dict[key]?.[lang] ?? dict[key]?.en ?? fallback ?? key,
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, toggle, t }), [lang, setLang, toggle, t]);

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang() {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used within LanguageProvider.");
  return ctx;
}
