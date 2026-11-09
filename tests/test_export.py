import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest

from blog import export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'vault'
        self.project = self.root / 'site'
        self.source.mkdir()
        (self.source / 'published').mkdir()
        self.project.mkdir()

    def write(self, name, text):
        if name.endswith('.md'):
            name = 'published/' + name
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_export(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return export(self.source, self.project)

    def post(self, name='post'):
        return (self.project / 'content' / 'posts' / name / 'index.md').read_text()

    def test_image_widths_order_and_bytes_are_preserved(self):
        original = self.write('post.md', 'Before\n\n![[screen one.png | 1]] ![[second.jpeg | 170]] ![[screen one.png|170x340]]\n\nAfter')
        image = self.write('img/screen one.png', 'original image bytes')
        self.write('img/second.jpeg', 'second image')
        self.write('img/unreferenced.png', 'do not copy')
        before = original.read_bytes()
        counts = self.run_export()
        content = self.post()
        self.assertIn('width="1"', content)
        self.assertIn('width="170" height="340"', content)
        self.assertIn('images/img/screen%20one.png', content)
        self.assertLess(content.index('width="1"'), content.index('second.jpeg'))
        self.assertEqual(content.count('<div class="image-row">'), 1)
        bundle = self.project / 'content/posts/post/images/img'
        self.assertEqual((bundle / image.name).read_bytes(), image.read_bytes())
        self.assertFalse((bundle / 'unreferenced.png').exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(counts, {'posts': 1, 'images': 2})

    def test_separate_image_paragraphs_stay_separate(self):
        self.write('post.md', '![[a.png]]\n\n![[a.png]]')
        self.write('a.png', 'bytes')
        self.run_export()
        self.assertEqual(self.post().count('<div class="image-row">'), 2)

    def test_markdown_images_and_external_images(self):
        self.write('post.md', '![Some & "description"](<img/my photo.png>)\n\n![Remote](https://example.com/image.png)')
        self.write('img/my photo.png', 'bytes')
        self.run_export()
        self.assertIn('alt="Some &amp; &quot;description&quot;"', self.post())
        self.assertIn('my%20photo.png', self.post())
        self.assertIn('![Remote](https://example.com/image.png)', self.post())

    def test_code_examples_are_not_exported_as_images(self):
        examples = '```markdown\n![[missing.png]]\n```\n\n`![[also-missing.png]]`\n\n~~~\n[[private note]]\n~~~\n'
        self.write('post.md', examples)
        self.run_export()
        self.assertIn(examples, self.post())

    def test_parent_relative_images_inside_source_are_supported(self):
        self.write('notes/post.md', '![[../../img/a.png|170]]\n\n![Photo](../../img/a.png)')
        self.write('img/a.png', 'image')
        self.run_export()
        self.assertEqual(self.post('notes-post').count('src="images/img/a.png"'), 2)

    def test_explicit_metadata_and_default_title(self):
        self.write('post.md', '---\ndate: 2024-01-02\ntitle: My chosen title\ndraft: true\n---\n\nContent')
        self.run_export()
        self.assertIn('date: 2024-01-02', self.post())
        self.assertIn('title: My chosen title', self.post())
        self.assertIn('draft: true', self.post())
        self.assertEqual(self.post().count('title:'), 1)

    def test_fallback_date_stays_stable_after_edit(self):
        path = self.write('post.md', 'First version')
        os.utime(path, (1700000000, 1700000000))
        self.run_export()
        first = self.post().split('date: ')[1].splitlines()[0]
        path.write_text('Updated version')
        self.run_export()
        self.assertIn('date: ' + first, self.post())
        self.assertIn('Updated version', self.post())

    def test_wikilinks_resolve_only_published_notes(self):
        self.write('post.md', '[[folder/Other|Read more]] and [[folder/Other#Some Heading]]')
        self.write('folder/Other.md', '# Some Heading\nHello')
        self.run_export()
        self.assertIn('[Read more](/posts/folder-other/)', self.post())
        self.assertIn('/posts/folder-other/#some-heading', self.post())

    def test_failed_export_keeps_last_good_content(self):
        path = self.write('post.md', 'Good version')
        self.run_export()
        previous = self.post()
        path.write_text('![[missing.png]]')
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.run_export()
        self.assertEqual(self.post(), previous)

    def test_ambiguous_attachments_are_rejected(self):
        self.write('post.md', '![[a.png]]')
        self.write('one/a.png', 'one')
        self.write('two/a.png', 'two')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.run_export()

    def test_outside_references_and_symlinks_are_rejected(self):
        outside = self.root / 'private.png'
        outside.write_text('private')
        self.write('post.md', '![[../private.png]]')
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.run_export()
        (self.source / 'leaked.png').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Symlinks outside'):
            self.run_export()

    def test_deleted_posts_and_unused_images_are_removed_on_reexport(self):
        self.write('post.md', '![[a.png]]')
        self.write('a.png', 'image')
        removed = self.write('removed.md', 'Old post')
        self.run_export()
        removed.unlink()
        self.write('post.md', 'No image anymore')
        self.run_export()
        self.assertFalse((self.project / 'content/posts/removed').exists())
        self.assertFalse((self.project / 'content/posts/post/images').exists())

    def test_colliding_urls_fail_without_replacing_content(self):
        self.write('post.md', 'Hello')
        self.run_export()
        self.write('Post.md', 'Collision')
        with self.assertRaisesRegex(ValueError, 'Conflicting post URL'):
            self.run_export()
        self.assertIn('Hello', self.post())

    def test_hidden_files_are_not_published(self):
        self.write('post.md', 'Public')
        self.write('.secret.md', 'Private')
        self.write('.obsidian/settings.md', 'Private')
        self.assertEqual(self.run_export()['posts'], 1)

    def test_only_published_notes_are_exported_with_shared_images(self):
        self.write('post.md', '![[shared.png|170]]')
        self.write('img/shared.png', 'image')
        (self.source / 'drafts').mkdir()
        (self.source / 'drafts/private.md').write_text('Private draft with ![[missing.png]]')
        (self.source / 'root.md').write_text('Not published')
        self.assertEqual(self.run_export(), {'posts': 1, 'images': 1})
        self.assertEqual([p.name for p in (self.project / 'content/posts').iterdir()], ['post'])
        self.assertIn('width="170"', self.post())

    def test_moving_last_post_to_drafts_clears_export(self):
        note = self.write('post.md', 'Published')
        self.run_export()
        (self.source / 'drafts').mkdir()
        note.rename(self.source / 'drafts/post.md')
        self.assertEqual(self.run_export()['posts'], 0)
        self.assertEqual(list((self.project / 'content/posts').iterdir()), [])

    def test_wikilinks_cannot_publish_drafts(self):
        self.write('post.md', '[[../drafts/private]]')
        (self.source / 'drafts').mkdir()
        (self.source / 'drafts/private.md').write_text('Private')
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.run_export()

    def test_symlinked_draft_cannot_be_published(self):
        draft = self.source / 'private.md'
        draft.write_text('Private')
        (self.source / 'published/leaked.md').symlink_to(draft)
        with self.assertRaisesRegex(ValueError, 'outside published/'):
            self.run_export()

    def test_missing_published_folder_does_not_fall_back_to_source(self):
        (self.source / 'published').rmdir()
        (self.source / 'private.md').write_text('Private')
        with self.assertRaisesRegex(ValueError, 'Published folder must exist'):
            self.run_export()

    def test_referenced_vault_root_images_are_supported_without_publishing_other_notes(self):
        (self.root / '.obsidian').mkdir()
        image = self.root / 'pasted.png'
        image.write_bytes(b'original bytes')
        (self.root / 'unused.png').write_bytes(b'not referenced')
        (self.root / 'private.md').write_text('Private note')
        self.write('post.md', '![[pasted.png|170]]')
        self.assertEqual(self.run_export(), {'posts': 1, 'images': 1})
        self.assertIn('src="images/vault/pasted.png"', self.post())
        destination = self.project / 'content/posts/post/images/vault/pasted.png'
        self.assertEqual(destination.read_bytes(), image.read_bytes())
        self.assertFalse(destination.with_name('unused.png').exists())

    def test_parent_images_are_not_allowed_without_detected_vault(self):
        (self.root / 'pasted.png').write_bytes(b'private bytes')
        self.write('post.md', '![[pasted.png]]')
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.run_export()


if __name__ == '__main__':
    unittest.main()
