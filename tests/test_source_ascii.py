"""ASCII gate fixtures use disposable repositories, not private runtime files."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_ascii', PROJECT / 'scripts/check_source_ascii.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceAsciiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '--quiet', '--template=')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args])

    def stage(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        self.git('add', '--', name)
        return path

    def test_unicode_escapes_and_literal_ascii_pass_for_code_and_role_files(self):
        self.stage('src/fixture.py', 'text = "\\u3042"\n')
        self.stage('.codex/agents/fixture.toml', 'description = "English role"\n')
        result = module.check(self.root)
        self.assertTrue(result['passed'])
        self.assertEqual(result['checked_sources'], 2)

    def test_literal_unicode_is_rejected_without_echoing_its_value(self):
        value = chr(0x3042)
        self.stage('src/fixture.py', '# first line\ntext = "' + value + '"\n')
        result = module.check(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual(result['findings'], [{'path': 'src/fixture.py', 'line': 2, 'rule': 'non_ascii_source'}])
        self.assertNotIn(value, str(result))

    def test_markdown_historical_bytes_are_not_rewritten_or_flagged(self):
        self.stage('src/fixture.py', '# ASCII source\n')
        path = self.stage('docs/original_jp.md', chr(0x3042) + '\n')
        before = path.read_bytes()
        self.assertTrue(module.check(self.root)['passed'])
        self.assertEqual(path.read_bytes(), before)

    def test_staged_blob_is_authoritative_not_an_unstaged_replacement(self):
        path = self.stage('src/fixture.py', 'text = "' + chr(0x3042) + '"\n')
        path.write_text('# unstaged ASCII replacement\n')
        self.assertFalse(module.check(self.root)['passed'])

    def test_symlink_source_is_not_followed(self):
        path = self.root / 'fixture.py'
        path.symlink_to('/nonexistent-private-fixture')
        self.git('add', '--', path.name)
        result = module.check(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual(result['findings'][0]['rule'], 'nonregular_or_conflicted_source')

    def test_empty_source_inventory_is_not_a_pass(self):
        self.stage('README.md', '# Documentation only\n')
        result = module.check(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checked_sources'], 0)


if __name__ == '__main__':
    unittest.main()
