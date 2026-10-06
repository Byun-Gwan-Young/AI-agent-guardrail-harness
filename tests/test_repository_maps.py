"""C-19-5 parts 2-3 : the repository map READMEs name only paths that exist (offline, read-only).

Checked in each map : relative markdown links (resolved from the README's folder), inline code spans that start with a
top-level tracked entry (resolved from the repository root; `*` is a glob that must match), the folder tree of the root
README, and the mermaid blocks' basic shape (diagram type, balanced brackets and quotes, subgraph/end).
Paths that are local-only by .gitignore (docs/handoff/, logs/demo/, runs/demo-batches/, raw session files) are skipped.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPS = ('README.md', 'scenarios/README.md', 'reports/README.md', 'tools/README.md', 'docs/README.md',
        'batch_plans/README.md')
LOCAL_ONLY = ('docs/handoff/', 'logs/demo/', 'runs/demo-batches/', 'runs/demo/<')
FENCE = re.compile(r'^```(\w*)\n(.*?)^```', re.M | re.S)
LINK = re.compile(r'\]\(([^)\s]+)\)')
CODE = re.compile(r'`([^`\n]+)`')
TREE_LINE = re.compile(r'^((?:│   |    )*)(?:├── |└── )(\S+)')


def tracked_top_level():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True).stdout.decode()
    return {p.split('/', 1)[0] for p in out.split('\0') if p}


def without_fences(text):
    return FENCE.sub('', text)


def exists(path):
    path = path.split(':', 1)[0].rstrip('/')
    if '*' in path:
        return any(ROOT.glob(path))
    return (ROOT / path).exists()


class RepositoryMapTest(unittest.TestCase):
    def setUp(self):
        self.tops = tracked_top_level()

    def text(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_maps_exist(self):
        for name in MAPS:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_relative_links_resolve(self):
        for name in MAPS:
            base = (ROOT / name).parent
            for target in LINK.findall(without_fences(self.text(name))):
                if re.match(r'[a-z]+:', target) or target.startswith('#'):
                    continue
                target = target.split('#', 1)[0]
                with self.subTest(map=name, link=target):
                    self.assertTrue((base / target).exists(), f'{name}: link {target}')

    def test_code_paths_exist(self):
        for name in MAPS:
            for span in CODE.findall(without_fences(self.text(name))):
                span = span.strip()
                if ' ' in span or '<' in span or '…' in span or span.startswith(LOCAL_ONLY):
                    continue
                first = span.split('/', 1)[0].split(':', 1)[0]
                if first not in self.tops:
                    continue
                with self.subTest(map=name, path=span):
                    self.assertTrue(exists(span), f'{name}: {span}')

    def tree(self):
        blocks = [body for lang, body in FENCE.findall(self.text('README.md'))
                  if lang == 'text' and body.startswith('AI-agent-guardrail-harness/')]
        self.assertEqual(len(blocks), 1)
        return blocks[0]

    def test_root_tree_entries_exist(self):
        stack, checked = [], 0
        for line in self.tree().splitlines()[1:]:
            match = TREE_LINE.match(line)
            if not match:
                continue
            depth = len(match.group(1)) // 4
            name = match.group(2)
            stack[depth:] = [name.rstrip('/')]
            path = '/'.join(stack)
            if (path + '/').startswith(LOCAL_ONLY):
                continue
            with self.subTest(entry=path):
                self.assertTrue(exists(path), f'tree entry {path}')
                if name.endswith('/') and '*' not in path:
                    self.assertTrue((ROOT / path).is_dir(), f'tree entry {path} is not a folder')
            checked += 1
        self.assertGreater(checked, 30)

    def test_root_tree_lists_every_tracked_top_level_entry(self):
        listed = {m.group(2).rstrip('/') for m in map(TREE_LINE.match, self.tree().splitlines()) if m and not m.group(1)}
        self.assertEqual(sorted(self.tops - listed), [])

    def test_no_html_comment_left_in_root_readme(self):
        self.assertNotIn('<!--', self.text('README.md'))

    def test_mermaid_blocks(self):
        for name in MAPS:
            for lang, body in FENCE.findall(self.text(name)):
                if lang != 'mermaid':
                    continue
                with self.subTest(map=name):
                    first = body.strip().splitlines()[0].split()[0]
                    self.assertIn(first, ('flowchart', 'graph', 'sequenceDiagram', 'stateDiagram-v2'))
                    opened = sum(1 for l in body.splitlines() if l.strip().startswith('subgraph '))
                    closed = sum(1 for l in body.splitlines() if l.strip() == 'end')
                    self.assertEqual(opened, closed)
                    for line in body.splitlines():
                        self.assertEqual(line.count('"') % 2, 0, line)
                        for a, b in ('[]', '()', '{}'):
                            self.assertEqual(line.count(a), line.count(b), line)


if __name__ == '__main__':
    unittest.main()
