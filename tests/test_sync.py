import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from blog import push_posts


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / 'site'
        self.remote = root / 'remote.git'
        self.project.mkdir()
        self.env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.com',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.com')
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main')
        self.posts = self.project / 'content/posts'
        self.posts.mkdir(parents=True)
        (self.posts / 'post.md').write_text('Original post')
        (self.project / 'settings.txt').write_text('Original settings')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial blog')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-u', 'origin', 'main')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.project, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def sync(self):
        from unittest.mock import patch
        with patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            push_posts(self.project)

    def test_only_posts_are_committed_and_pushed(self):
        (self.posts / 'post.md').write_text('Updated post')
        (self.posts / 'image.png').write_bytes(b'image bytes')
        (self.project / 'settings.txt').write_text('Unrelated edit')
        self.sync()
        self.assertEqual(self.git('show', 'origin/main:content/posts/post.md'), 'Updated post')
        self.assertEqual(self.git('show', 'origin/main:settings.txt'), 'Original settings')
        self.assertEqual(self.git('status', '--porcelain'), 'M settings.txt')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))

    def test_no_changes_does_not_create_empty_commit(self):
        before = self.git('rev-parse', 'HEAD')
        self.sync()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)

    def test_existing_unpushed_commit_is_pushed(self):
        (self.posts / 'post.md').write_text('Previously committed update')
        self.git('add', 'content/posts')
        self.git('commit', '-m', 'Update blog posts')
        before = self.git('rev-parse', 'HEAD')
        self.sync()
        self.assertEqual(self.git('rev-parse', 'origin/main'), before)

    def test_removing_all_posts_is_committed(self):
        (self.posts / 'post.md').unlink()
        self.sync()
        self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'origin/main', 'content/posts'), '')

    def test_staged_edits_are_preserved_and_not_pushed(self):
        (self.project / 'settings.txt').write_text('Staged edit')
        self.git('add', 'settings.txt')
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'already staged'):
            self.sync()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('diff', '--cached', '--name-only'), 'settings.txt')

    def test_wrong_branch_is_not_pushed(self):
        self.git('switch', '-c', 'experiment', '--track', 'origin/main')
        with self.assertRaisesRegex(ValueError, 'requires main'):
            self.sync()
