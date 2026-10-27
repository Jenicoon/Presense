const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
(async () => {
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-audio-capture=${process.env.COACH_TEST_AUDIO || "/private/tmp/coach-voice.wav"}`,
    ],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    permissions: ["camera", "microphone"],
  });
  await context.addInitScript(() =>
    localStorage.setItem("presense-lang", "ko"),
  );
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  try {
    await page.goto("http://localhost:3015");
    await page.locator("input[type=email]").fill("coach@example.test");
    await page.locator("input[type=password]").fill("test-password");
    console.log(await page.locator("button").allTextContents());
    await page.locator(".auth-form-card .btn-primary").click();
    await page.waitForURL("**/dashboard");
    await page.goto(
      "http://localhost:3015/history?session=22222222-2222-4222-8222-222222222222",
    );
    await page.locator(".actual-timeline").waitFor();
    await page.screenshot({
      path: "/private/tmp/coach-report-browser.png",
      fullPage: true,
    });
    console.log("gaps", await page.locator(".actual-timeline .gap").count());
    await page
      .locator(".actual-timeline button:not([disabled])")
      .nth(2)
      .click();
    const seek = await page
      .locator(".history-review-video video")
      .evaluate((v) => v.currentTime);
    if (Math.abs(seek - 25) > 1) throw Error("Timeline did not seek to 25s");
    console.log("seekTime", seek);
    await page
      .getByRole("button", { name: "이 구간 함께 확인하기" })
      .first()
      .click();
    await page.locator(".agent-panel .coach-video").first().waitFor();
    console.log("coach", await page.locator(".agent-panel").innerText());
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "이 부분을 연습하고 싶어요", exact: true })
      .last()
      .click();
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "재연습 녹화 시작", exact: true })
      .waitFor();
    await page.reload();
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "재연습 녹화 시작", exact: true })
      .waitFor();
    console.log("RESTORE_OK");
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "재연습 녹화 시작", exact: true })
      .click();
    await page.waitForURL("**/practice?coaching=*");
    console.log("practice page");
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll("video")).some(
        (v) => v.videoWidth > 0,
      ),
    );
    const enableMic = page.getByRole("button", {
      name: "마이크 활성화",
      exact: true,
    });
    if (await enableMic.isVisible()) await enableMic.click();

    await page
      .getByRole("button", { name: "준비 완료", exact: true })
      .waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: "준비 완료", exact: true }).click();
    await page.getByRole("button", { name: "세션 시작", exact: true }).click();
    console.log("RECORDING_STARTED");
    await page.waitForTimeout(32000);
    await page.getByRole("button", { name: "세션 종료", exact: true }).click();
    await page.locator(".agent-panel").getByRole("button", { name: "의도한 전달이 됐어요", exact: true }).waitFor({ timeout: 30000 });
    await page.locator(".agent-panel").getByRole("button", { name: "의도한 전달이 됐어요", exact: true }).click();
    await page
      .locator(".agent-panel .coach-components")
      .getByText("달성", { exact: true })
      .waitFor({ timeout: 30000 });
    console.log("COMPARISON_READY");
    await page.locator(".save-modal-backdrop .save-modal-close").click();
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("button")).some(
          (b) => b.textContent.trim() === "세션 시작" && !b.disabled,
        ),
      { timeout: 30000 },
    );
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "같은 연습 다시 하기", exact: true })
      .last()
      .click();
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll("button")).some(
        (b) => b.textContent.trim() === "세션 종료" && !b.disabled,
      ),
    );
    console.log("RETRY_RECORDING_STARTED_FROM_CHAT");
    await page.waitForTimeout(12000);
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "녹화 종료 및 분석", exact: true })
      .last()
      .click();
    await page
      .locator(".agent-panel .coach-components")
      .getByText("자료 부족", { exact: true })
      .last()
      .waitFor({ timeout: 30000 });
    console.log("SHORT_RETRY_INSUFFICIENT_AS_EXPECTED");

    await page.screenshot({
      path: "/private/tmp/coach-comparison-browser.png",
      fullPage: true,
    });
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "다음 목표 선택", exact: true })
      .last()
      .click();
    await page
      .locator(".agent-panel")
      .getByRole("button", { name: "핵심 문장 하나에만 강조 주기", exact: true })
      .last()
      .click();
    await page
      .locator(".agent-panel-message.agent")
      .filter({
        hasText: "다음 목표로 ‘핵심 문장 하나에만 강조 주기’ 항목을 선택했습니다.",
      })
      .last()
      .waitFor();
    await page
      .locator(".agent-panel .coach-choices button:enabled")
      .filter({ hasText: /^목표 저장하고 마치기$/ })
      .last()
      .click();
    await page
      .getByText("코칭 결과와 다음 목표를 저장했습니다.", { exact: true })
      .waitFor();
    const state = await (
      await context.request.get("http://127.0.0.1:8015/test/state")
    ).json();
    const doc = state.documents["22222222-2222-4222-8222-222222222222"];
    if (doc.state.stage !== "completed" || !doc.state.nextGoalId)
      throw Error("Goal not persisted");
    const firstTake =
      state.documents[doc.practices[0].attemptSessionId].snapshot.request;
    if (
      firstTake.durationMs < 30000 ||
      firstTake.segments.length < 2 ||
      new Set(firstTake.segments.map((w) => w.stressScore)).size < 2
    )
      throw Error("32-second take lost multiple actual responses");
    console.log("FIRST_TAKE_WINDOWS", firstTake.segments.length);
    const attempt = state.documents[doc.state.attemptSessionId];
    const windows = attempt.snapshot.request.segments;
    if (
      windows.length < 2 ||
      new Set(windows.map((w) => w.stressScore)).size < 2
    )
      throw Error("Actual multiple responses were lost");
    console.log(
      "SAVED_GOAL_OK",
      doc.state.nextGoalId,
      "RETRY_WINDOWS",
      windows.length,
    );
    await page.locator(".save-modal-backdrop .save-modal-close").click();
    const cell = page
      .locator(".session-agent-report .actual-timeline button:not([disabled])")
      .nth(1);
    await cell.click();
    const retrySeek = await page
      .locator(".session-video-review video")
      .evaluate((v) => v.currentTime);
    if (retrySeek <= 0) throw Error("Retry recording did not seek");
    console.log("RETRY_VIDEO_SEEK_OK", retrySeek);
    await page.screenshot({
      path: "/private/tmp/coach-comparison-browser.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: "/private/tmp/coach-mobile-browser.png",
      fullPage: true,
    });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    if (overflow) throw Error("Mobile horizontal overflow");
    if (errors.length) throw Error(errors.join(" | "));
    const previousCard = page.locator(".agent-panel .coach-video").first();
    await previousCard.click();
    await page.waitForURL("**/history?session=*&at=*");
    await page.waitForFunction(() => {
      const v = document.querySelector(".history-review-video video");
      return v && v.currentTime >= 24.5;
    });
    console.log("CROSS_PAGE_VIDEO_CARD_SEEK_OK");
    console.log("errors", errors);
    console.log("coaching", await page.locator(".agent-panel").innerText());
  } catch (e) {
    console.log("FAIL", e.stack);
    console.log("page", await page.locator("body").innerText());
    await page.screenshot({
      path: "/private/tmp/coach-failed-browser.png",
      fullPage: true,
    });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
