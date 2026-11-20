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
expected = {
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
assert actual_files == set(manifest) | (set(expected) - {'index.html', 'privacy/index.html'})
print('PASS complete 27-file landing manifest and exact site inventory')
css = (root / 'assets/site.css').read_text()
assert not re.search(r'@import|expression\s*\(|javascript:', css, re.I)
for value in re.findall(r'url\(([^)]+)\)', css):
    value = value.strip('\"\' ')
    resolved = urljoin('/assets/site.css', value)
    assert resolved.startswith('/assets/') and resolved[1:] in manifest, value
print('PASS CSS resources are local; no imports or active content')

actual = {p.relative_to(root).as_posix() for p in root.rglob('*.html')
          if '.git' not in p.relative_to(root).parts}
assert actual == set(expected), actual
for filename, (digest, links) in expected.items():
    path = root / filename
    assert not path.is_symlink(), filename
    data = path.read_bytes()
    assert sha256(data).hexdigest() == digest, filename
    text = data.decode('utf-8')
    assert text.startswith('<!doctype html>\n')
    parser = Landing() if filename == 'index.html' else Check()
    parser.feed(text)
    parser.close()
    assert not parser.stack
    if links is not None:
        assert parser.links == links
    else:
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
