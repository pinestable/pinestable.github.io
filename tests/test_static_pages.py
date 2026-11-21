"""Dependency-free checks for the approved static pages and optional aliases."""
from pathlib import Path
from html.parser import HTMLParser
from hashlib import sha256
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from threading import Thread
from urllib.request import urlopen
from urllib.parse import urlsplit, urljoin
import re
import json

root = Path(__file__).resolve().parents[1]
privacy_hash = 'fdb93667aa06a567da94e4d5de17f5876fe361d61e37ec198266f89841b15dda'
privacy_links = ['https://gumroad.com/privacy', 'mailto:leon.pinestable@agentmail.to']
practice_path = 'learning-apps/practice/index.html'
practice_hash = 'ad33f2e8f906636df63b582d86b1f6da9cdd827518a47e98b1509048efcf6deb'
practice_links = [
    '#tasks',
    '#q01',
    '#q04',
    '#q09',
    '#q15',
    'https://support.microsoft.com/en-us/excel/protect-a-worksheet',
    'https://support.microsoft.com/en-us/excel/get-started/apply-data-validation-to-cells',
    'https://support.microsoft.com/en-us/excel/more-on-data-validation',
    'https://support.microsoft.com/en-gb/excel/functions/sumifs-function?nochrome=true',
    'https://support.microsoft.com/en-us/excel/excel-functions-by-category',
    'https://support.microsoft.com/en-us/excel/available-chart-types-in-office',
    'https://support.microsoft.com/en-us/office/change-the-display-of-chart-axes',
    'https://support.microsoft.com/en-us/excel/present-your-data-in-a-scatter-chart-or-a-line-chart',
    '#setup-heading',
]
expected = {
    practice_path: (practice_hash, practice_links),
    'index.html': ('40827437f1aa56fea348e4e462ca9abb79fda0ae44f7c3b045da6120f5b9ab38',
                   None),
    'privacy/index.html': (privacy_hash, privacy_links),
}
for alias in ('PineStable/privacy/index.html', 'pinestable-privacy-policy/index.html'):
    if (root / alias).exists():
        expected[alias] = (privacy_hash, privacy_links)
        assert (root / alias).read_bytes() == (root / 'privacy/index.html').read_bytes()
        print('PASS alias equals original:', alias)

allowed = {'html': {'lang'}, 'head': set(), 'meta': {'charset', 'name', 'content'}, 'title': set(), 'body': set(), 'main': set(), 'h1': set(), 'p': set(), 'a': {'href'}}
class Check(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.links = [], []
    def handle_starttag(self, tag, attrs):
        assert tag in allowed, tag
        assert all(k in allowed[tag] for k, v in attrs), attrs
        assert len(dict(attrs)) == len(attrs)
        if tag == 'meta':
            assert dict(attrs) in [{'charset': 'utf-8'}, {'name': 'viewport', 'content': 'width=device-width, initial-scale=1'}]
        else:
            self.stack.append(tag)
        if tag == 'a': self.links.append(dict(attrs)['href'])
    def handle_endtag(self, tag):
        assert self.stack.pop() == tag, tag
    def handle_comment(self, data):
        raise AssertionError('Unexpected comment')



# Privacy keeps its original strict parser. The landing page has a separate schema.
class Landing(Check):
    tags = {
        'html', 'head', 'meta', 'title', 'link', 'body', 'a', 'header', 'svg',
        'path', 'span', 'nav', 'ul', 'li', 'main', 'div', 'section', 'h1', 'h2',
        'h3', 'p', 'dl', 'dt', 'dd', 'ol', 'article', 'img', 'data', 'footer',
    }
    attrs = {
        'class', 'id', 'lang', 'charset', 'name', 'content', 'property', 'rel',
        'href', 'sizes', 'type', 'as', 'crossorigin', 'aria-label', 'viewbox',
        'aria-hidden', 'focusable', 'd', 'aria-labelledby', 'role', 'style',
        'src', 'srcset', 'width', 'height', 'alt', 'decoding', 'loading', 'value',
    }

    def __init__(self):
        super().__init__()
        self.ids, self.fragments, self.images = set(), [], 0

    def local(self, value):
        assert value.startswith('/') and not value.startswith('//'), value
        assert value.lstrip('/') in manifest, value

    def handle_starttag(self, tag, attrs):
        assert tag in self.tags, tag
        assert len(dict(attrs)) == len(attrs), attrs
        a = dict(attrs)
        assert set(a) <= self.attrs, attrs
        if 'id' in a:
            assert a['id'] not in self.ids
            self.ids.add(a['id'])
        if 'style' in a:
            assert tag == 'li' and re.fullmatch(r'--ply:#[0-9a-f]{6}', a['style'])
        if tag == 'meta':
            assert 'http-equiv' not in a
        if tag == 'a':
            href = a['href']
            self.links.append(href)
            if href.startswith('#'):
                self.fragments.append(href[1:])
            elif href.startswith('/'):
                assert href in ('/', '/privacy/')
            elif href.startswith('mailto:'):
                assert href == 'mailto:leon.pinestable@agentmail.to'
            else:
                u = urlsplit(href)
                assert u.scheme == 'https' and u.netloc in {
                    'pinestable.gumroad.com', 'www.etsy.com', 'www.pinterest.com'}
        if tag == 'link':
            if a['rel'] == 'canonical':
                assert a['href'] == 'https://pinestable.github.io/'
            else:
                assert a['rel'] in {'icon', 'apple-touch-icon', 'preload', 'stylesheet'}
                self.local(a['href'])
        if tag == 'img':
            self.images += 1
            assert a['alt'] and int(a['width']) > 0 and int(a['height']) > 0
            self.local(a['src'])
            for item in a.get('srcset', '').split(','):
                if item.strip():
                    self.local(item.strip().split()[0])
        if tag not in {'meta', 'link', 'img'}:
            self.stack.append(tag)

# This schema applies only to the registered practice page, never privacy pages.
class Practice(Check):
    schema = {
        'html': {'lang'}, 'head': set(), 'title': set(), 'style': set(),
        'meta': {'charset', 'name', 'content'}, 'body': set(),
        'a': {'class', 'href'}, 'header': set(), 'footer': set(),
        'div': {'class'}, 'h1': set(), 'h2': {'id'}, 'h3': set(),
        'p': {'class', 'id'}, 'section': {'aria-labelledby'},
        'nav': {'aria-label'}, 'ul': set(), 'ol': set(), 'li': set(),
        'main': {'id', 'tabindex'}, 'article': {'id', 'aria-labelledby'},
        'label': {'for', 'class'},
        'textarea': {'id', 'rows', 'readonly', 'spellcheck'},
        'details': set(), 'summary': set(), 'code': {'class', 'tabindex', 'role', 'aria-labelledby'},
        'input': {'type'},
    }

    def __init__(self):
        super().__init__()
        self.ids, self.references, self.articles = set(), [], []
        self.reveals = self.summaries = self.boxes = self.checkboxes = 0

    def handle_starttag(self, tag, attrs):
        assert tag in self.schema, f'practice tag: {tag}'
        a = dict(attrs)
        assert len(a) == len(attrs), 'practice duplicate attribute'
        assert set(a) <= self.schema[tag], f'practice attributes: {tag}'
        if 'id' in a:
            assert a['id'] not in self.ids, 'practice duplicate id'
            self.ids.add(a['id'])
        for key in ('for', 'aria-labelledby'):
            if key in a:
                self.references.extend(a[key].split())
        if tag == 'meta':
            assert a in [
                {'charset': 'utf-8'},
                {'name': 'viewport', 'content': 'width=device-width, initial-scale=1'},
                {'name': 'referrer', 'content': 'no-referrer'},
            ] or (set(a) == {'name', 'content'} and a['name'] == 'description'), 'practice meta'
        if tag == 'a':
            self.links.append(a['href'])
            if a['href'].startswith('#'):
                self.references.append(a['href'][1:])
        if tag == 'article':
            self.articles.append(a['id'])
        if tag == 'details':
            assert self.stack[-1] == 'article', 'practice reveal nesting'
            self.reveals += 1
        if tag == 'summary':
            assert self.stack[-1] == 'details', 'practice summary nesting'
            self.summaries += 1
        if tag == 'code' and a.get('class') == 'formula':
            assert a == {'class': 'formula', 'tabindex': '0', 'role': 'region',
                         'aria-labelledby': 'q09-formula-label'}, 'practice formula keyboard access'
        if tag == 'textarea':
            assert a.get('readonly', False) is None and a.get('spellcheck') == 'false', 'practice readonly data'
            self.boxes += 1
        if tag == 'input':
            assert a == {'type': 'checkbox'} and self.stack[-1] == 'label', 'practice checkbox'
            self.checkboxes += 1
        if tag not in {'meta', 'input'}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, 'practice nesting'

    def handle_data(self, data):
        if self.stack and self.stack[-1] == 'style':
            assert not re.search(r'url\s*\(|@import|expression\s*\(|javascript:|\\', data, re.I), 'practice CSS resource'

    def close(self):
        super().close()
        assert not self.stack, 'practice unclosed markup'
        assert set(self.references) <= self.ids, 'practice reference'
        assert self.articles == ['q01', 'q04', 'q09', 'q15'], 'practice task inventory'
        assert (self.reveals, self.summaries, self.boxes, self.checkboxes) == (4, 4, 4, 4), 'practice controls'


def check_inventory(actual_files, actual_html):
    assert actual_files == set(manifest) | (set(expected) - {'index.html', 'privacy/index.html'}), 'site inventory'
    assert actual_html == set(expected), 'HTML inventory'


def check_digest(data, digest, filename):
    assert sha256(data).hexdigest() == digest, f'approved digest: {filename}'


def check_markup(filename, text, links):
    parser = (Landing() if filename == 'index.html' else
              Practice() if filename == practice_path else Check())
    parser.feed(text)
    parser.close()
    assert not parser.stack, 'unclosed markup'
    if links is not None:
        assert parser.links == links, f'exact links: {filename}'
    return parser


manifest = {}
for line in (root / 'tests/landing.sha256').read_text().splitlines():
    digest, name = line.split()
    name = name.removeprefix('./')
    assert name not in manifest and '..' not in Path(name).parts
    manifest[name] = digest
assert len(manifest) == 27
for name, digest in manifest.items():
    path = root / name
    assert not any(p.is_symlink() for p in [path, *path.parents])
    assert sha256(path.read_bytes()).hexdigest() == digest, name
actual_files = {p.relative_to(root).as_posix() for p in root.rglob('*')
                if p.is_file() and p.relative_to(root).parts[0] not in {'.git', '.github', 'tests'}}
actual = {p.relative_to(root).as_posix() for p in root.rglob('*.html')
          if '.git' not in p.relative_to(root).parts}
check_inventory(actual_files, actual)
print('PASS complete 27-file landing manifest and exact site inventory')
css = (root / 'assets/site.css').read_text()
assert not re.search(r'@import|expression\s*\(|javascript:', css, re.I)
for value in re.findall(r'url\(([^)]+)\)', css):
    value = value.strip('\"\' ')
    resolved = urljoin('/assets/site.css', value)
    assert resolved.startswith('/assets/') and resolved[1:] in manifest, value
print('PASS CSS resources are local; no imports or active content')

for filename, (digest, links) in expected.items():
    path = root / filename
    assert not path.is_symlink(), filename
    data = path.read_bytes()
    check_digest(data, digest, filename)
    text = data.decode('utf-8')
    assert text.startswith('<!doctype html>\n')
    parser = check_markup(filename, text, links)
    if links is None:
        assert parser.images == 8
        assert set(parser.fragments) <= parser.ids
        assert '/privacy/' in parser.links
        products = json.loads((root / 'tests/landing-products.json').read_text())
        assert len(products) == 8
        assert {link for link in parser.links if 'gumroad.com/l/' in link} == {
            product['gumroad_url'] for product in products}
        for product in products:
            start = text.rfind('<li class="line', 0, text.index(product['gumroad_url']))
            segment = text[start:text.index('</li>', start)]
            assert product['title'] in segment.replace('&amp;', '&')
            assert f'<data value="{product["price"]:g}">{product["price"]:g}</data>' in segment
            assert '>USD<' in segment
            assert f'/assets/covers/{product["id"]}-480.webp' in segment
            if product.get('etsy_url'):
                assert product['etsy_url'] in segment
        print('PASS eight product titles, USD prices, cover paths and marketplace links')
    assert len(re.findall(r'<h1(?:\s[^>]*)?>', text)) == 1
    assert '<html lang="en">' in text
    print('PASS approved SHA-256, static markup and links:', filename)

def rejects(reason, action):
    try:
        action()
    except AssertionError as error:
        assert reason in str(error), f'wrong failure: {error}; expected {reason}'
    else:
        raise AssertionError(f'negative control accepted: {reason}')
    print('PASS negative control:', reason)


# Exercise guards independently so a digest mismatch cannot mask parser/link failures.
rejects('site inventory', lambda: check_inventory(actual_files | {'unregistered.txt'}, actual))
rejects('HTML inventory', lambda: check_inventory(actual_files, actual | {'tests/unregistered.html'}))
practice_data = (root / practice_path).read_bytes()
practice_text = practice_data.decode('utf-8')
rejects('approved digest', lambda: check_digest(practice_data + b'\n', practice_hash, practice_path))
for old, new, reason in [
    (practice_links[5], 'https://example.com/', 'exact links'),
    ('<body>', '<body><script></script>', 'practice tag: script'),
    ('<body>', '<body onload="alert(1)">', 'practice attributes'),
    ('<style>', '<style>@import "https://example.com/x.css";', 'practice CSS resource'),
    ('<summary>', '<summary onclick="alert(1)">', 'practice attributes'),
    ('id="q15"', 'id="q16"', 'practice reference'),
    ('tabindex="0"', 'tabindex="-1"', 'practice formula keyboard access'),
    ('readonly spellcheck', 'spellcheck', 'practice readonly data'),
]:
    assert old in practice_text
    rejects(reason, lambda old=old, new=new: check_markup(
        practice_path, practice_text.replace(old, new, 1), practice_links))
for filename, (digest, links) in expected.items():
    if digest != privacy_hash:
        continue
    data = (root / filename).read_bytes()
    text = data.decode('utf-8')
    rejects('approved digest', lambda: check_digest(data + b'\n', digest, filename))
    rejects('exact links', lambda: check_markup(filename, text.replace(
        privacy_links[0], 'https://example.com/'), links))
    # Practice-only markup must still fail the original privacy parser.
    rejects('details', lambda: check_markup(filename, text.replace(
        '<body>', '<body><details></details>'), links))


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(root)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for filename in dict.fromkeys([*manifest, *expected]):
        route = '/' + filename.removesuffix('index.html')
        with urlopen(f'http://127.0.0.1:{server.server_port}{route}', timeout=5) as response:
            assert response.status == 200
            assert response.read() == (root / filename).read_bytes()
            assert response.headers.get('Set-Cookie') is None
        print('PASS local HTTP 200, exact bytes, no cookies:', route)
finally:
    server.shutdown()
    server.server_close()
    thread.join()
