# Exact7 V2 런타임과 코칭 검증

기존 `weights/` 모델과 기존 세션은 보존한다. 새 모델은 별도 `weights/concept_v2/` 번들을 사용하며 `PRESENSE_MODEL_VARIANT=concept-v2`로 명시적으로 선택한다. 기본값은 `legacy`다. 새 모델의 배포 성능이 더 좋다고 주장하거나 기존 예측의 이름만 바꾸지 않는다.

## 데이터 계약

모델 버전은 Student·head·투영·정규화·측정 정의의 해시를 포함한다. 현재 번들의 모델 ID는 `exact7-v2-1ce99c975e6e62ba176b`, 측정 정의는 `session-analysis-v5-exact7`, concept 정의는 `literature-exact7-v2`다. 세션/분석창의 버전 불일치는 거절하며 다른 버전으로 생성된 이전 세션·재연습에는 비교 점수를 생성하지 않는다. 기존 Supabase JSON 저장 필드를 그대로 활용한다.

7개 순서는 평균 F0, jitter, shimmer, HNR, 좌우 browDown 평균, 좌우 eyeSquint 평균, jawOpen이다. F0의 원래 단위는 eGeMAPS semitone이며 Hz로 잘못 표시하지 않는다. 실제 원시 측정값과 0–1의 보조 concept 예측값은 별개로 표시한다. 예측값의 크기를 모달리티 기여도로 표현하지 않는다.

새 Student의 `geo_gru.pool.score.*` 구조와 새 head의 `state_dict`를 strict load한다. 식은 `base logits + 0.03 × concept correction`, temperature 1이다. 누락된 특징 추출기나 잘못된 차원에 영벡터를 대신 넣지 않는다.

음성 투영은 복구된 Student SHA와 짝을 이루며 훈련 참가자로 적합하고 별도 참가자 121개 입력으로 검증했다. R² 0.998861, MAE 0.004430. 기존 배포 geometry scaler의 작은 두 분산 처리로는 원래 캐시를 재현하지 못해 훈련 참가자의 raw/normalized 쌍으로 affine 변환을 복원했다. 별도 참가자의 최대 오차는 5.96e-8이다. eGeMAPS 입력의 역사적 전체 코호트 정규화는 재현을 위해 유지했으므로 독립적인 전처리 검증이라고 해석하면 안 된다. Concept p2/p98은 훈련 참가자 기준이다.

## 재현 명령

저장소 루트와 프로젝트의 모델 의존성이 있는 Python 환경에서 실행한다. SOURCE는 실험 결과와 캐시가 있는 기존 체크아웃의 경로다.

```sh
python -m server.package_concept_v2 --source-root "$SOURCE" --output-dir /tmp/new-concept-v2-bundle
python -m server.verify_concept_v2 --source-root "$SOURCE" --output /tmp/v2-offline.json
PRESENSE_V2_SOURCE_ROOT="$SOURCE" python -m unittest discover -s server/tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
```

패키징 도구는 기존 출력 디렉터리를 덮어쓰지 않는다. 체크포인트/정규화/투영의 해시를 검사하며 SHA 검사 우회는 없다. 검증 캐시나 데이터셋은 Git에 추가하지 않는다.

## 확인한 결과

- 고정된 121개 입력의 전체 forward 결과: 97/121 (80.1653%). 기존 복구 Student의 99/121보다 분류 성능이 높지 않다.
- 순서대로 concept R²: 0.8549, 0.7226, 0.7420, 0.8796, 0.8453, 0.8099, 0.7784. 평균 0.8047.
- 고정 예측과 최대 오차: base logits 5.96e-7, concept 4.17e-7.
- 로컬 실제 10초/16프레임 입력을 HTTP `/infer`로 전송하여 7개 예측과 raw 4개 음성/3개 영상 측정, 품질 및 버전을 확인했다. 외부 LLM 호출은 없다.
- 별도 60초 로컬 예시에서 실제 11개 창과 서로 다른 11개 점수를 보존했다. 5초 stride/10초 창의 합집합은 60초, coverage 100%다. 기존 미리보기 세션과 연습 기록은 보존했다.
- browDown, eyeSquint, jawOpen에 대한 실제 로컬 논문 검색과 측정 관련성 검사를 통과했다. 근거는 관련 문맥이며 연습 효과나 인과관계의 검증이 아니다.
- 화면에서 한국어/영어 전환, 실제 측정/예측 구분, 25초 타임라인 클릭 후 영상 이동을 확인했다.
- 최종 서버 테스트 152개, 프론트 테스트 37개, 타입 검사 및 별도 V2 프로덕션 빌드가 통과했다.
- 실제 로컬 StressID 코칭 요청은 외부 호출 없이 503으로 차단되는 것을 확인했다.

## 실제 AI 검증과 개인정보 경계

사용자가 승인한 범위는 합성 자료 또는 본인 촬영 테스트다. 이 검증에서는 **상수로 만든 합성 자료만 Luxia에 전송**했다. StressID/외부 참가자 자료, 원본 영상·음성, 계정 정보, 실제 파일명은 보내지 않았다. 새로운 UUID와 상대 시각, 7개 raw 측정, 품질, 합성 점수, 필요한 최소 문맥만 사용했다. 문헌은 DOI/출처와 짧은 관련 발췌만 전달했다.

```sh
python -m server.verify_concept_v2_ai --env-file /path/to/server/.env --rag-dir /path/to/local/paper-index --output-dir /tmp/new-synthetic-audit
```

이 도구는 파일/계정/실제 세션 식별자와 합성 이외의 provenance를 전송 직전에 거절하고, HTTP 헤더를 제외한 실제 payload와 응답을 먼저 로컬에 기록한다. 중단된 검증은 `--resume-synthetic-audit`로 이어갈 수 있지만 하드코딩된 합성 fixture와 모든 값이 정확히 같아야 한다. 일반 세션/참가자 자료를 가져오는 기능이 아니다. 합성 점수는 모델을 돌려 얻은 점수가 아니다.

AI의 선택, 생성 문안, 서버 거절 이유, 재시도 및 시간 초과를 포함한 이번 감사 자료는 Git에서 제외한 `local-validation/concept-v2-ai/`에 보관한다. 첫 AI 선택의 보고서를 이어서 실제 코칭 응답과 연습 생성 검증을 수행했다. 최종 실행은 13회 호출로 `finding_selected → practice_created`와 안정적인 예시의 발견 0개를 통과했다. 연습 안내는 AI가 생성한 목표·성공 기준에서 구성하며 같은 검증을 거친다. AI가 임의의 수치·시각·원인·무관한 조언을 생성하면 검증에서 차단하며, 응답 장애를 성공으로 숨기지 않는다. 단일 JSON fence 밖의 해설은 표시하지 않으며 두 번째 JSON은 거절한다.

StressID 로컬 미리보기는 외부 AI 코칭을 비활성화한다. 영상/타임라인/측정은 계속 로컬에서 열람할 수 있다. 본인 촬영의 일반 코칭 흐름은 유지한다.

## 해석의 한계

이전에도 확인한 참가자 분할을 사용했으므로 새로운 독립 최종 시험이 아니다. Eye-squint의 내부 fold 최저 R²는 0.357이었다. 단일 concept를 평균으로 바꾸어도 정답 수가 달라지지 않았으므로 concept 추가가 분류 정확도를 높였다는 주장은 할 수 없다. 점수는 과제 라벨로 학습한 모델의 신호이며 순간 스트레스, 감정 진단 또는 의학적 수치가 아니다.

턱 움직임이 크다는 이유로 줄이도록 지시하지 않는다. 실제 소리를 듣고 급하게 이어졌는지 사용자가 확인한 경우에만 의미가 끝나는 쉼을 연습한다. 눈 주변 연습도 움직임 수치 감소를 달성 기준으로 삼지 않는다. 발표 내용·발음·청중 반응은 현재 측정으로 판단할 수 없다. 실제 카메라/마이크를 통한 본인 재촬영과 운영 Supabase에 대한 최종 검증은 별도로 필요하다.
