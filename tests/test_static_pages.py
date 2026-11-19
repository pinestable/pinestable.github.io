"""Dependency-free checks for the approved static pages and optional aliases."""
from pathlib import Path
from html.parser import HTMLParser
from hashlib import sha256
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from threading import Thread
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
privacy_hash = 'fdb93667aa06a567da94e4d5de17f5876fe361d61e37ec198266f89841b15dda'
privacy_links = ['https://gumroad.com/privacy', 'mailto:leon.pinestable@agentmail.to']
expected = {
    'index.html': ('cbbb742ca2bbd16a6f75fcbcd74ad7130f7f9bc6e9910c8f1a916cecd09587bd',
                   ['https://pinestable.gumroad.com/', '/privacy/']),
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
    parser = Check()
    parser.feed(text)
    parser.close()
    assert not parser.stack
    assert parser.links == links
    assert text.count('<h1>') == 1
    assert '<html lang="en">' in text
    print('PASS approved SHA-256, static markup and links:', filename)

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(root)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for filename in expected:
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
