"""C-19-5 part 0 : tracked-file inventory with path-reference counts (read-only, no network).

Reference sources are every tracked text file except session logs (logs/, runs/*/session.json, runs/*/steps.json and
any file over 256 KiB), plus the PM guideline docs/handoff/시나리오_수집_가이드라인.md (untracked, read if present).
A file's own text never counts as a reference to itself.

    venv/bin/python reports/c19-5/inventory.py            # writes reports/c19-5/inventory.json and inventory.md
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDELINE = "docs/handoff/시나리오_수집_가이드라인.md"
MAX_SOURCE_BYTES = 256 * 1024
FREEZE = "docs/criteria/demo-final-freeze.json"


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def is_session_log(path, size):
    name = path.rsplit("/", 1)[-1]
    return (path.startswith("logs/") or (path.startswith("runs/") and name in ("session.json", "steps.json"))
            or size > MAX_SOURCE_BYTES)


def frozen_paths():
    data = json.loads((ROOT / FREEZE).read_text(encoding="utf-8"))
    paths = set(data["files"])
    paths.update(data["criteria_freeze"]["implementation_sha256"])
    paths.update(p for p in tracked() if p.startswith("docs/criteria/"))
    paths.update(p for p in tracked() if re.fullmatch(r"guardrail-deadlock-v0\.[23].*\.yaml", p))
    paths.update(p for p in tracked() if re.fullmatch(r"deadlock_policy(_v0[123])?\.py", p))
    return paths


def classify(path, frozen):
    top = path.split("/", 1)[0]
    if path in frozen:
        return "동결"
    if top in ("runs", "logs"):
        return "실행 기록"
    if top == "batch_plans":
        return "계획"
    if top == "tests":
        return "테스트"
    if top == "tools":
        return "도구"
    if top == "reports":
        return "보고"
    if top == "docs" or path == "README.md":
        return "문서"
    if top in ("experiments", "scenario_judges") or (("/" not in path) and path.endswith(".py")
                                                      and path not in ("test.py", "models.py", "deadlock_test.py")):
        return "실행 코드"
    if top in ("scenarios", "scenario_assets") or path in ("requirements.txt", "guardrail.yaml",
                                                           "demo-conditions.yaml"):
        return "실행 코드"
    return "기타"


def describe(path):
    p = ROOT / path
    try:
        if p.stat().st_size > MAX_SOURCE_BYTES:
            return ""
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    if path.endswith(".md"):
        for line in text.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
    if path.endswith(".py"):
        m = re.match(r'\s*(?:#![^\n]*\n)?\s*(?:"""|\'\'\')\s*(.+)', text)
        if m:
            return m.group(1).strip().rstrip('"').strip()
        for line in text.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
    if path.endswith((".yaml", ".yml")):
        for key in ("description", "title", "scenario_id", "plan_id", "id"):
            m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
            if m:
                return f"{key}: {m.group(1).strip()}"
    if path.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return ""
        if isinstance(data, dict):
            for k, v in data.items():
                if k.endswith("_version") and isinstance(v, str):
                    return f"{k}: {v}"
            return "keys: " + ", ".join(list(data)[:4])
        if isinstance(data, list):
            return f"list of {len(data)}"
    return ""


PATTERNS = [
    (r"^reports/.*/tests[^/]*\.json$", "오프라인 테스트 실행 결과 (run_offline_tests 출력)"),
    (r"^reports/.*-preflight\.json$", "시나리오 실행 전 기록 (scenario_preflight 출력)"),
    (r"^reports/.*/replay[^/]*/.*\.html$", "세션 재생 페이지 (replay_demo 출력)"),
    (r"^reports/.*-manifest\.json$", "세션 매니페스트"),
    (r"^reports/.*-analysis\.json$", "세션 사후 분석 (analyze_session 출력)"),
    (r"^tests/fixtures/", "테스트 고정 자료"),
    (r"^tests/test_.*\.py$", "오프라인 테스트"),
]


def describe_ko(path, what):
    for pattern, text in PATTERNS:
        if re.search(pattern, path):
            return text
    return what


def untracked_summary():
    out = subprocess.run(["git", "status", "--ignored", "--porcelain", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout.decode("utf-8")
    groups = Counter()
    for entry in out.split("\0"):
        if not entry:
            continue
        state, path = entry[:2], entry[3:]
        parts = path.rstrip("/").split("/")
        key = "/".join(parts[:2]) + ("/" if path.endswith("/") or len(parts) > 2 else "")
        groups[("무시됨" if state == "!!" else "추적 안 됨", key)] += 1
    return [{"state": s, "path": p, "entries": n} for (s, p), n in sorted(groups.items())]


def md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_markdown(out, target):
    lines = ["# C-19-5 파트 0 — 저장소 목록 (바꾸기 전)", "",
             "> `reports/c19-5/inventory.py` 출력 (읽기 전용, 외부 호출 없음). 손으로 고친 값 없음. "
             "기준 커밋 `" + out["git_commit"] + "`.", "",
             "## 1. 요약", "",
             f"- 추적 파일 {out['tracked_files']} 개. 참조를 센 원문 {out['sources_scanned']} 개 "
             f"(추적 텍스트 파일 + 가이드라인 `{GUIDELINE}`, 가이드라인 읽음 : {out['guideline_read']})",
             f"- 참조를 세지 않은 대형 세션 로그 {len(out['sources_skipped_session_logs'])} 개 "
             "(`logs/`, `runs/*/session.json`·`steps.json`, 256 KiB 초과) — 열지 않음",
             "- 참조 수 : **전체 경로** 문자열, **파일 이름**(마지막 경로 조각), `.py` 는 **모듈 이름**(점·하이픈·글자가 붙지 않은 "
             "낱말) 을 따로 셈. 자기 자신 안의 문자열은 세지 않음. 이름 수는 겹치는 다른 파일까지 세므로 위쪽 값이다",
             "", "| 분류 | 파일 수 |", "|---|---|"]
    for cat in ("동결", "실행 코드", "실행 기록", "계획", "테스트", "도구", "문서", "보고", "기타"):
        lines.append(f"| {cat} | {out['category_counts'].get(cat, 0)} |")
    lines += ["", "분류 규칙 : **동결** = 최종 동결 62 파일 + v0.3 구현 해시 대상 + `docs/criteria/` + "
              "`guardrail-deadlock-v0.2*`·`v0.3*` 설정 + `deadlock_policy*.py`. **실행 코드** = 루트의 실행 모듈, "
              "`experiments/`, `scenarios/`, `scenario_assets/`, `scenario_judges/`, 실행 설정. **실행 기록** = `runs/`, "
              "`logs/`. 나머지는 폴더 이름대로. 초기 Groq 시험 스크립트·로그(`test.py` 등)는 **기타**", ""]
    by_path = {r["path"]: r for r in out["files"]}
    header = ["| 경로 | 무엇인지 | 분류 | 참조 (전체 경로 / 이름 / 모듈) | 가이드라인 |", "|---|---|---|---|---|"]

    def row(r):
        mod = r["refs_module_name"] if r["path"].endswith(".py") else "—"
        return (f"| `{md_cell(r['path'])}` | {md_cell(describe_ko(r['path'], r['what']))} | {r['category']} | "
                f"{r['refs_full_path']} / {r['refs_basename']} / {mod} | {r['refs_in_guideline']} |")

    lines += ["## 2. 루트 파일", ""] + header
    lines += [row(r) for r in out["files"] if "/" not in r["path"]]
    lines += ["", "## 3. 폴더", "", "| 폴더 | 파일 수 | 폴더 밖 참조 (폴더 경로 문자열) | 가이드라인 |", "|---|---|---|---|"]
    for f in out["folders"]:
        if f["folder"].count("/") <= 1 or not f["folder"].startswith(("runs/", "logs/")):
            lines.append(f"| `{md_cell(f['folder'])}/` | {f['files']} | {f['refs_outside']} | {f['refs_in_guideline']} |")
    lines += ["", "## 4. 파일 (실행 기록 제외)", ""]
    tops = sorted({p.split("/", 1)[0] for p in by_path if "/" in p and not p.startswith(("runs/", "logs/"))})
    for top in tops:
        lines += [f"### `{top}/`", ""] + header
        lines += [row(r) for r in out["files"] if r["path"].startswith(top + "/")]
        lines.append("")
    lines += ["## 5. 실행 기록 (`runs/`, `logs/`) — 세션 폴더 단위", "",
              "실행 기록은 DM-84 ① 대로 옮기지 않는다. 파일 하나하나 대신 폴더 단위로 적는다.", "",
              "| 폴더 | 파일 수 | 폴더 밖 참조 |", "|---|---|---|"]
    seen = Counter()
    for p in by_path:
        if p.startswith("runs/"):
            parts = p.split("/")
            seen["/".join(parts[:3]) if parts[1] == "demo" and len(parts) > 3 else "/".join(parts[:2])] += 1
    folder_refs = {f["folder"]: f["refs_outside"] for f in out["folders"]}
    for key, n in sorted(seen.items()):
        lines.append(f"| `{key}/` | {n} | {folder_refs.get(key, '—')} |")
    for r in out["files"]:
        if r["path"].startswith("logs/"):
            lines.append(f"| `{r['path']}` | 1 | {r['refs_full_path']} |")
    lines += ["", "## 6. 추적되지 않는 것과 `.gitignore`", "",
              "`git status --ignored` 를 두 단계 경로로 묶음. 지우지 않는다.", "",
              "| 상태 | 경로 | 항목 수 |", "|---|---|---|"]
    for u in out["untracked"]:
        lines.append(f"| {u['state']} | `{md_cell(u['path'])}` | {u['entries']} |")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    lines += ["", "`.gitignore` 의 규칙 줄 : " + ", ".join(f"`{g}`" for g in gitignore if g and not g.startswith("#")),
              "", "## 7. 옮길 수 있는 후보 (참조 0)", "",
              "분류가 문서·보고·기타이고 전체 경로·이름·모듈 참조가 모두 0 인 파일.", "",
              "| 경로 | 분류 | 무엇인지 |", "|---|---|---|"]
    for r in out["files"]:
        if r["category"] in ("문서", "보고", "기타") and not (r["refs_full_path"] or r["refs_basename"]
                                                         or r["refs_module_name"]):
            lines.append(f"| `{md_cell(r['path'])}` | {r['category']} | {md_cell(describe_ko(r['path'], r['what']))} |")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_sources(files):
    sources = {}
    for path in files:
        p = ROOT / path
        size = p.stat().st_size
        if is_session_log(path, size):
            continue
        try:
            sources[path] = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    g = ROOT / GUIDELINE
    if g.exists():
        sources[GUIDELINE] = g.read_text(encoding="utf-8")
    return sources


def count_refs(needle, sources, exclude=()):
    total, where = 0, 0
    for path, text in sources.items():
        if path in exclude:
            continue
        n = text.count(needle)
        if n:
            total += n
            where += 1
    return total, where


def main():
    files = tracked()
    frozen = frozen_paths()
    sources = load_sources(files)
    guideline = sources.get(GUIDELINE, "")
    rows = []
    for path in files:
        name = path.rsplit("/", 1)[-1]
        full, full_files = count_refs(path, sources, exclude=(path,))
        base, base_files = count_refs(name, sources, exclude=(path,))
        stem_hits = 0
        if path.endswith(".py"):
            stem = name[:-3]
            pat = re.compile(rf"(?<![\w.-]){re.escape(stem)}(?![\w-])")
            stem_hits = sum(len(pat.findall(t)) for p, t in sources.items() if p != path)
        rows.append({
            "path": path,
            "category": classify(path, frozen),
            "what": describe(path),
            "refs_full_path": full,
            "refs_full_path_files": full_files,
            "refs_basename": base,
            "refs_basename_files": base_files,
            "refs_module_name": stem_hits,
            "refs_in_guideline": guideline.count(path) + (guideline.count(name) if name != path else 0),
        })
    folders = sorted({p.rsplit("/", 1)[0] for p in files if "/" in p})
    folder_rows = []
    for folder in folders:
        inside = [p for p in files if p.startswith(folder + "/")]
        refs, ref_files = count_refs(folder, sources, exclude=tuple(inside))
        folder_rows.append({"folder": folder, "files": len(inside), "refs_outside": refs,
                            "refs_outside_files": ref_files, "refs_in_guideline": guideline.count(folder)})
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True).stdout.decode().strip()
    out = {
        "inventory_version": "c19-5-inventory-v1",
        "git_commit": head,
        "tracked_files": len(files),
        "sources_scanned": len(sources),
        "sources_skipped_session_logs": sorted(p for p in files if is_session_log(p, (ROOT / p).stat().st_size)),
        "guideline_read": GUIDELINE in sources,
        "category_counts": dict(Counter(r["category"] for r in rows)),
        "files": rows,
        "folders": folder_rows,
        "untracked": untracked_summary(),
    }
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports/c19-5/inventory.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_markdown(out, target.with_suffix(".md"))
    print(json.dumps({k: out[k] for k in ("tracked_files", "sources_scanned", "guideline_read",
                                          "category_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
