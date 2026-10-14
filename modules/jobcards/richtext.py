"""Task notes are small pieces of formatted text (bold, italic, underline, bullet lists) kept as HTML.

The browser's editor produces that HTML, but nothing it sends is trusted: every note is rebuilt here from an allow list
of tags with no attributes at all, so a note can never carry a script, a link, a style or an event handler. Notes are
cleaned when they are saved and again when they are read, so what reaches a page is always the cleaned form.
"""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser

ALLOWED = {"b", "strong", "i", "em", "u", "ul", "ol", "li", "br", "p", "div"}
VOID = {"br"}
DROP_WITH_CONTENT = {"script", "style", "textarea", "title", "template", "iframe", "object", "noscript"}
MAX_LENGTH = 20000          # characters of cleaned HTML per note


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open = []          # allowed tags currently open, so the result is always well formed
        self.skipping = 0       # inside a tag whose content is dropped as well

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skipping += 1
        elif not self.skipping and tag in ALLOWED:
            self.out.append(f"<{tag}>")
            if tag not in VOID:
                self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID and not self.skipping:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skipping = max(0, self.skipping - 1)
        elif not self.skipping and tag in self.open:
            while self.open:                                  # close anything left open inside it
                self.out.append(f"</{self.open[-1]}>")
                if self.open.pop() == tag:
                    break

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _text(cleaned: str) -> str:
    """Just the words of a cleaned note, to tell a note with something in it from one with only blank lines."""
    parser = _Text()
    parser.feed(cleaned)
    return "".join(parser.parts).replace("\xa0", " ").strip()


class _Plain(HTMLParser):
    BLOCKS = {"br", "div", "p", "li", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []

    def _break(self, tag):
        if tag in self.BLOCKS and self.out and not self.out[-1].endswith("\n"):
            self.out.append("\n")

    def handle_starttag(self, tag, attrs):
        self._break(tag)

    def handle_endtag(self, tag):
        self._break(tag)

    def handle_data(self, data):
        self.out.append(data)


def plain(cleaned: str, limit: int = 1000) -> str:
    """A note as plain text, one line per paragraph or list item. Used where only text can go (a heading's description)."""
    parser = _Plain()
    parser.feed(cleaned or "")
    lines = [" ".join(line.split()) for line in "".join(parser.out).replace("\xa0", " ").split("\n")]
    return "\n".join(line for line in lines if line)[:limit]


def clean(raw) -> str:
    """A note as safe HTML. A note with nothing in it (blank lines only) becomes ''. Raises ValueError if too long."""
    if not raw or not isinstance(raw, str):
        return ""
    parser = _Cleaner()
    parser.feed(raw)
    parser.close()
    cleaned = parser.result().strip()
    if not _text(cleaned) and "<li>" not in cleaned:
        return ""
    if len(cleaned) > MAX_LENGTH:
        raise ValueError(f"A note can be at most {MAX_LENGTH:,} characters including its formatting")
    return cleaned
