import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  filterSessions,
  fromApi,
  groupedStats,
  stepFromApi,
} from "../src/model.js";
const reference = JSON.parse(
  readFileSync(new URL("../public/records.json", import.meta.url)),
);

test("curated records retain the 67-session baseline and separate modes", () => {
  assert.equal(reference.sessions.length, 67);
  assert.equal(
    filterSessions(reference.sessions, { mode: "observe" }).length,
    54,
  );
  assert.equal(
    filterSessions(reference.sessions, { mode: "block" }).length,
    13,
  );
  assert.equal(
    groupedStats(reference.sessions).reduce((n, g) => n + g.count, 0),
    67,
  );
});
test("filters combine task, mode, variant and search", () => {
  const rows = filterSessions(reference.sessions, {
    task: "DEMO-CT",
    mode: "observe",
    variant: "stall",
    search: "승인",
  });
  assert.ok(rows.length > 0);
  assert.ok(
    rows.every(
      (r) =>
        r.task === "DEMO-CT" && r.mode === "observe" && r.variant === "stall",
    ),
  );
});
test("API adapters preserve zero values, missing measurements, and server roles", () => {
  const s = fromApi({
    session_id: "abc",
    first_stop_step: 0,
    credits_measured: 0,
    credits_estimated: 9,
  });
  assert.equal(s.first_stop, 0);
  assert.equal(s.credits, 0);
  assert.equal(s.tokens, undefined);
  const f = stepFromApi(
    {
      step_id: 3,
      agent: "dev",
      state: "stagnant",
      tests: { passed: 0, total: 8 },
      stop: { template_id: "E1", text: "reason" },
      report: { open_issue_ids: ["x"], handoff_to: "review" },
      tools: [{ is_error: true }],
      tokens: { prompt: 10, completion: 2 },
    },
    { dev: "개발", review: "검토" },
  );
  assert.deepEqual(f.tests, [0, 8]);
  assert.equal(f.role, "개발");
  assert.equal(f.stop.t, "E1");
  assert.equal(f.report.handoff, "검토");
  assert.equal(f.tool_errors, 1);
  assert.equal(f.tok, 12);
  assert.equal(
    stepFromApi({ step_id: 1, tests: {}, report: {}, stop: {} }).tests,
    null,
  );
});
