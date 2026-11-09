#!/usr/bin/env python3
"""Export a publishing folder from Obsidian and run Hugo. Python 3.11+."""

import argparse
from datetime import date, datetime
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = Path('/home/rubem/Downloads/rubem/personal')
HUGO_VERSION = '0.147.9'
IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif', '.bmp'}


def slug(value):
    value = re.sub(r'[^\w.-]+', '-', value.lower()).strip('-.')
    if not value:
        raise ValueError('A note filename must contain letters or numbers.')
    return value


def export(source, project=ROOT):
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f'Source folder does not exist: {source}')
    published = source / 'published'
    if not published.is_dir() or published.is_symlink():
        raise ValueError(f'Published folder must exist and not be a symlink: {published}')
    files = sorted(p for p in source.rglob('*')
                   if p.is_file() and not any(part.startswith('.') for part in p.relative_to(source).parts))
    for path in files:
        if not path.resolve().is_relative_to(source):
            raise ValueError(f'Symlinks outside the publishing folder are not allowed: {path}')
    notes = [p for p in files if p.suffix.lower() == '.md' and p.is_relative_to(published)]
    for note in notes:
        if not note.resolve().is_relative_to(published):
            raise ValueError(f'Published notes cannot link to files outside published/: {note}')
    note_urls = {}
    for note in notes:
        url = '/posts/' + slug(note.relative_to(published).with_suffix('').as_posix().replace('/', '-')) + '/'
        if url in note_urls.values():
            raise ValueError(f'Conflicting post URL: {url}')
        note_urls[note] = url

    state_dir = project / '.blog'
    state_dir.mkdir(parents=True, exist_ok=True)
    dates_path = state_dir / 'dates.json'
    dates = json.loads(dates_path.read_text()) if dates_path.exists() else {}
    counts = {'posts': 0, 'images': 0}

    def resolve(target, note, candidates=files):
        target = unquote(target).strip()
        for path in (note.parent / target, published / target, source / target):
            path = path.resolve()
            if path.is_relative_to(source) and path in candidates:
                return path
        matches = [p for p in candidates if p.name == target or p.relative_to(source).as_posix() == target]
        if len(matches) != 1:
            reason = 'not found' if not matches else 'ambiguous'
            raise ValueError(f'{note.relative_to(source)}: reference {target!r} is {reason} inside the publishing folder')
        return matches[0]

    # Complete the export before replacing anything, so broken references retain the last good preview.
    with tempfile.TemporaryDirectory(prefix='export-', dir=state_dir) as temporary:
        staging = Path(temporary) / 'posts'
        staging.mkdir()
        for note in notes:
            relative = note.relative_to(source).as_posix()
            bundle = staging / note_urls[note].removeprefix('/posts/').rstrip('/')
            bundle.mkdir(parents=True)
            text = note.read_text(encoding='utf-8')
            metadata = ''
            if text.startswith('---\n'):
                match = re.match(r'\A---\n(.*?)\n---(?:\n|$)', text, re.S)
                if not match:
                    raise ValueError(f'{relative}: unclosed YAML front matter')
                metadata, text = match.group(1), text[match.end():]
            elif text.startswith('+++\n'):
                raise ValueError(f'{relative}: use YAML front matter (---), not TOML (+++)')
            if not re.search(r'^title\s*:', metadata, re.M):
                title = note.stem.replace('_', ' ').replace('-', ' ')
                metadata += '\ntitle: ' + json.dumps(title, ensure_ascii=False)
            date_match = re.search(r'^date\s*:\s*(.+)', metadata, re.M)
            if date_match:
                stamp = date_match.group(1).split(' #')[0].strip().strip('\"\'')
                date.fromisoformat(stamp[:10])
            else:
                key = str(source / note.relative_to(published))
                if key not in dates:
                    dates[key] = datetime.fromtimestamp(note.stat().st_mtime).date().isoformat()
                metadata += '\ndate: ' + dates[key]

            copied = set()

            def image(target, alt='', size=''):
                path = resolve(target, note)
                if path.suffix.lower() not in IMAGE_TYPES:
                    raise ValueError(f'{relative}: unsupported image type: {target}')
                destination = bundle / 'images' / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if path not in copied:
                    shutil.copyfile(path, destination)
                    copied.add(path)
                    counts['images'] += 1
                url = quote(destination.relative_to(bundle).as_posix(), safe='/')
                dimensions = re.fullmatch(r'\s*(\d+)(?:\s*x\s*(\d+))?\s*', size)
                if size and not dimensions:
                    raise ValueError(f'{relative}: unsupported image size: {size!r}')
                attrs = ''
                if dimensions:
                    attrs = f' width="{int(dimensions[1])}"'
                    if dimensions[2]:
                        attrs += f' height="{int(dimensions[2])}"'
                label = alt or path.stem
                return f'<img src="{url}" alt="{html.escape(label, quote=True)}"{attrs} loading="lazy" decoding="async">'

            def wiki_image(match):
                parts = match[1].split('|', 1)
                return image(parts[0].strip(), size=parts[1].strip() if len(parts) > 1 else '')

            def markdown_image(match):
                target = match[2].strip()
                if target.startswith('<'):
                    target = target[1:target.index('>')]
                else:
                    target = re.split(r'\s+[\"\']', target, maxsplit=1)[0]
                if urlsplit(target).scheme or target.startswith('//'):
                    return match[0]
                return image(target, alt=match[1])

            def wiki_link(match):
                target, _, label = match[1].partition('|')
                target, separator, anchor = target.partition('#')
                if target:
                    linked = resolve(target if target.endswith('.md') else target + '.md', note, notes)
                    url = note_urls[linked]
                else:
                    url = ''
                if separator:
                    url += '#' + slug(anchor)
                return f'[{label or target or anchor}]({url})'

            # Code examples are text, not attachment references. Protect both fenced and inline code.
            code_pattern = r'(^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\2[ \t]*(?:\n|$)|`+[^`\n]*`+)'
            protected = []

            def protect(match):
                protected.append(match[0])
                return f'\x00CODE{len(protected) - 1}\x00'

            text = re.sub(code_pattern, protect, text, flags=re.M | re.S)
            text = re.sub(r'!\[\[([^\]\n]+)\]\]', wiki_image, text)
            text = re.sub(r'!\[([^\]\n]*)\]\((<[^>]+>|[^)\n]+)\)', markdown_image, text)
            text = re.sub(r'(?<!!)\[\[([^\]\n]+)\]\]', wiki_link, text)
            # Images sharing a paragraph form one row, just as in Obsidian reading view.
            text = re.sub(r'(?:^|(?<=\n))([ \t]*<img\b[^>]*>(?:[ \t]+<img\b[^>]*>)*[ \t]*)(?=\n|$)',
                          lambda m: '<div class="image-row">' + m[1].strip() + '</div>\n', text)
            text = re.sub(r'\x00CODE(\d+)\x00', lambda m: protected[int(m[1])], text)
            (bundle / 'index.md').write_text('---\n' + metadata.strip() + '\n---\n\n' + text, encoding='utf-8')
            counts['posts'] += 1

        content = project / 'content'
        content.mkdir(exist_ok=True)
        previous = state_dir / 'previous-posts'
        if previous.exists():
            shutil.rmtree(previous)
        output = content / 'posts'
        if output.exists():
            output.rename(previous)
        staging.rename(output)
        if previous.exists():
            shutil.rmtree(previous)
        dates_path.write_text(json.dumps(dates, indent=2) + '\n')
    print(f'Exported {counts["posts"]} posts and {counts["images"]} image references from {source}', flush=True)
    return counts


def hugo(install=False):
    local = ROOT / '.tools' / 'hugo'
    if local.is_file():
        return str(local)
    existing = shutil.which('hugo')
    if existing:
        return existing
    if not install:
        raise ValueError('Hugo is not installed. Run: python3 blog.py setup')
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or not machine:
        raise ValueError('Install Hugo for your platform: https://gohugo.io/installation/')
    archive_name = f'hugo_{HUGO_VERSION}_linux-{machine}.tar.gz'
    base = f'https://github.com/gohugoio/hugo/releases/download/v{HUGO_VERSION}/'
    print(f'Downloading Hugo {HUGO_VERSION} to .tools/ ...', flush=True)
    archive = urlopen(base + archive_name, timeout=60).read()
    checksums = urlopen(base + f'hugo_{HUGO_VERSION}_checksums.txt', timeout=30).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == archive_name)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError('Hugo download checksum mismatch')
    local.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryFile() as temporary:
        temporary.write(archive)
        temporary.seek(0)
        with tarfile.open(fileobj=temporary, mode='r:gz') as tar:
            binary = tar.extractfile('hugo')
            if binary is None:
                raise ValueError('Hugo binary missing from download')
            local.write_bytes(binary.read())
    local.chmod(0o755)
    return str(local)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'export', 'serve', 'build'])
    parser.add_argument('--source', type=Path, default=Path(os.environ.get('OBSIDIAN_BLOG_SOURCE', str(DEFAULT_SOURCE))))
    parser.add_argument('--port', type=int, default=1313)
    parser.add_argument('--base-url', help='Public website URL (for build only)')
    args = parser.parse_args()
    if args.command == 'setup':
        subprocess.run([hugo(install=True), 'version'], check=True)
        return
    binary = hugo() if args.command != 'export' else None
    export(args.source)
    if args.command == 'serve':
        assert binary is not None
        print(f'Preview: http://localhost:{args.port}/ (Ctrl+C to stop)', flush=True)
        subprocess.run([binary, 'server', '--bind', '127.0.0.1', '--port', str(args.port),
                        '--buildDrafts', '--buildFuture', '--disableFastRender'], cwd=ROOT, check=True)
    elif args.command == 'build':
        assert binary is not None
        command = [binary, '--cleanDestinationDir', '--gc']
        if args.base_url:
            command += ['--baseURL', args.base_url]
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
