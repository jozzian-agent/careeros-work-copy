"""Deliberately small markdown subset with no HTML or link passthrough."""
from html import escape
import re

def render_markdown(text):
    def inline(value):
        value = escape(value)
        value = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', value)
        return re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', value)
    parts, paragraph, items = [], [], []
    def flush():
        if paragraph:
            parts.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()
        if items:
            parts.append('<ul>' + ''.join('<li>' + inline(x) + '</li>' for x in items) + '</ul>')
            items.clear()
    for line in text.splitlines():
        if not line.strip():
            flush()
        elif re.match(r'^\s*[-*] ', line):
            if paragraph:
                flush()
            items.append(re.sub(r'^\s*[-*] ', '', line))
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    return ''.join(parts)
