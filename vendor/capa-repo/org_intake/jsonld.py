"""Minimal JSON-LD block scanner.

Extracted from careeros/intake.py's Posting(HTMLParser) class: only the
<script type="application/ld+json"> block-collection concern, not the rest
of the posting parser (title/description/etc extraction), per the
contract's settled JSON-LD open question. This module never fetches a
page itself; it only scans HTML already handed to it (see enrich.py for
the fetch-then-scan wrapper).
"""
from html.parser import HTMLParser


class JsonLdScanner(HTMLParser):
    def __init__(self):
        super().__init__()
        self.json_blocks = []
        self._buffer = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and (attrs.get('type') or '').lower() == 'application/ld+json':
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == 'script' and self._buffer is not None:
            self.json_blocks.append(''.join(self._buffer))
            self._buffer = None

    def handle_data(self, value):
        if self._buffer is not None:
            self._buffer.append(value)


def scan(html):
    """Return every <script type="application/ld+json"> block's raw text
    content found in html, in document order. Each block's text is not
    parsed as JSON here; a block that is not valid JSON is still returned,
    left for the caller to attempt json.loads on and skip if it fails."""
    scanner = JsonLdScanner()
    scanner.feed(html)
    return scanner.json_blocks
