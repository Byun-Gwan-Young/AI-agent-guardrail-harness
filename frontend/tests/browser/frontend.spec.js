import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const data = JSON.parse(
  readFileSync(new URL("../../public/records.json", import.meta.url)),
);
const user = {
  id: 1,
  name: "테스트 사용자",
  email: "test@example.com",
  account_status: "active",
  session_scope: "full",
  csrf_token: "test-only-csrf",
};

test("preview navigation, combined filters, replay, comparison and responsive layout", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?preview=1");
  await expect(
    page.getByRole("heading", { name: "대시보드", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("54", { exact: true })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("dashboard.png"),
    fullPage: true,
  });
  await page.getByLabel("모드 필터").selectOption("block");
  await expect(page.getByText(/총 13개/)).toBeVisible();
  await page.getByLabel("시나리오 필터").selectOption("DEMO-CL");
  await expect(page.getByText(/총 3개/)).toBeVisible();
  await page
    .getByRole("button", { name: "코드 버그 수정 · 교착판", exact: true })
    .first()
    .click();
  await expect(page.getByRole("heading", { name: /1단계/ })).toBeVisible();
  await page.getByRole("button", { name: "다음 단계", exact: true }).click();
  await expect(page.getByRole("heading", { name: /2단계/ })).toBeVisible();
  await page.getByRole("button", { name: "첫 STOP으로" }).click();
  await expect(page.locator(".stop-message")).toBeVisible();
  for (const name of [
    "비교",
    "통계",
    "시스템 구조",
    "사용 가이드",
    "실시간 모니터",
    "프로젝트",
    "API 키 관리",
    "내 계정",
  ]) {
    await page
      .getByRole("navigation")
      .getByRole("button", { name, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name, exact: true }).first(),
    ).toBeVisible();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "대시보드", exact: true })
    .click();
  await expect(page.locator(".sidebar")).not.toHaveClass(/expanded/);
  await expect(page.locator(".sidebar")).toBeHidden();
  const dimensions = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    blocks: [
      ...document.querySelectorAll(
        ".app,.main-shell,main,.panel,.metrics,.dashboard-grid,footer,.topbar",
      ),
    ].map((e) => ({
      name: e.className || e.tagName,
      width: e.getBoundingClientRect().width,
      right: e.getBoundingClientRect().right,
    })),
  }));
  expect(dimensions.document, JSON.stringify(dimensions)).toBeLessThanOrEqual(
    dimensions.viewport + 1,
  );
  await page.screenshot({
    path: test.info().outputPath("mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("anonymous session renders React login; server errors do not become demo successes", async ({
  page,
}) => {
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: "{}" }),
  );
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "실험 워크스페이스에 로그인" }),
  ).toBeVisible();
  await page.unroute("**/api/auth/me");
  await page.route("**/api/auth/me", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("DB");
  await expect(page.getByText("54", { exact: true })).toHaveCount(0);
});

test("authenticated API, project create with CSRF, API failure and polling cleanup", async ({
  page,
}) => {
  const calls = [];
  let created = false;
  let liveCalls = 0;
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const respond = (body, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/auth/me") return respond(user);
    if (path === "/api/frontend/reference") return respond(data);
    if (path === "/api/summary")
      return respond({
        headline: data.headline,
        judgement_ms: data.judgement_ms,
      });
    if (path === "/api/sessions")
      return respond({
        count: data.sessions.length,
        sessions: data.sessions.map((s) => ({
          session_id: s.id,
          task: s.task,
          scenario_id: s.scenario,
          variant: s.variant,
          mode: s.mode,
          class: s.class,
          steps: s.steps,
          tokens_total: s.tokens,
          first_stop_step: s.first_stop,
          role_labels: s.roles,
        })),
      });
    if (path.startsWith("/api/sessions/")) {
      const s = data.sessions.find(
        (s) => s.id === decodeURIComponent(path.split("/")[3]),
      );
      if (!s) return respond({}, 404);
      if (path.endsWith("/steps"))
        return respond({
          steps: s.step_rows.map((f) => ({
            step_id: f.n,
            agent: f.agent,
            role: f.role,
            state: f.state,
            state_label: f.label,
            stop: f.stop ? { template_id: f.stop.t, text: f.stop.text } : null,
            blocked: f.blocked,
            tests: f.tests ? { passed: f.tests[0], total: f.tests[1] } : null,
            tokens: { prompt: f.tok, completion: 0 },
            cumulative_tokens: f.cum,
            changed_paths: f.paths,
          })),
        });
      return respond({
        session: { scenario: { korean_name: s.name, title: s.title } },
      });
    }
    if (path === "/api/projects" && req.method() === "POST") {
      calls.push(req.postDataJSON());
      created = true;
      return respond({ id: 1, name: "로컬 실험", mode: "observe" }, 201);
    }
    if (path === "/api/projects")
      return respond(
        created
          ? [
              {
                id: 1,
                name: "로컬 실험",
                mode: "observe",
                rule_id: "deadlock-v0.3",
              },
            ]
          : [],
      );
    if (path === "/api/projects/1/sessions")
      return respond({
        items: [
          {
            id: "owned-session",
            scenario_id: 1,
            status: "completed",
            started_at: "2026-11-01T00:00:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      });
    if (path === "/api/projects/1/sessions/owned-session")
      return respond({
        id: "owned-session",
        scenario_id: 1,
        status: "completed",
        steps_reached: 7,
      });
    if (path === "/api/live/sessions") {
      liveCalls++;
      return respond({ now: new Date().toISOString(), sessions: [] });
    }
    return respond({ detail: "Not found" }, 404);
  });
  await page.goto("/");
  await expect(page.locator(".data-toolbar")).toContainText(
    "DB 조회 API · 집계와 세션",
  );
  await page.locator(".table-link").first().click();
  await expect(page.getByRole("heading", { name: /1단계/ })).toBeVisible();
  await page.getByRole("button", { name: "다음 단계", exact: true }).click();
  await expect(page.getByRole("heading", { name: /2단계/ })).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "프로젝트", exact: true })
    .click();
  await page.getByLabel("프로젝트 이름").fill("로컬 실험");
  await page
    .getByRole("button", { name: "프로젝트 만들기", exact: true })
    .click();
  await expect(page.getByRole("button", { name: /로컬 실험/ })).toBeVisible();
  expect(calls).toEqual([
    { name: "로컬 실험", mode: "observe", csrf_token: user.csrf_token },
  ]);
  await page.getByRole("button", { name: /로컬 실험/ }).click();
  await page
    .getByRole("button", { name: "owned-session", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "프로젝트 세션 상세" }),
  ).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "실시간 모니터", exact: true })
    .click();
  await expect.poll(() => liveCalls).toBeGreaterThan(0);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "대시보드", exact: true })
    .click();
  const count = liveCalls;
  await page.waitForTimeout(2800);
  expect(liveCalls).toBe(count);
  await page.route("**/api/summary", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: "{}" }),
  );
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("DB");
});
