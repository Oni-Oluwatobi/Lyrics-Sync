"""Query normalization for Lyric Sync search.

Turns whatever the user typed into a stable, comparable representation:

* case folding
* Unicode composition / compatibility
* optional diacritic removal
* apostrophe unification (``'`` ``’`` ``῾`` …) and removal
* punctuation removal
* whitespace collapsing
* contraction handling
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

APOSTROPHES = "'’ʻʼ`´ʽ῾‛′"

# Common English contractions. The key is the canonical (apostrophe-free) form.
CONTRACTIONS: dict[str, str] = {
    "dont": "do not",
    "doesnt": "does not",
    "didnt": "did not",
    "cant": "can not",
    "cannot": "can not",
    "wont": "will not",
    "isnt": "is not",
    "arent": "are not",
    "wasnt": "was not",
    "werent": "were not",
    "hasnt": "has not",
    "havent": "have not",
    "hadnt": "had not",
    "wouldnt": "would not",
    "couldnt": "could not",
    "shouldnt": "should not",
    "im": "i am",
    "ive": "i have",
    "ill": "i will",
    "id": "i would",
    "youre": "you are",
    "youve": "you have",
    "youll": "you will",
    "youre": "you are",
    "hes": "he is",
    "shes": "she is",
    "its": "it is",
    "thats": "that is",
    "theres": "there is",
    "theyre": "they are",
    "theyve": "they have",
    "weve": "we have",
    "were": "we are",
    "whos": "who is",
    "whats": "what is",
    "lets": "let us",
    "ain": "is not",
}

# Words that carry little identifying signal on their own.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "is", "are", "was",
    "were", "be", "been", "being", "am", "i", "you", "he", "she", "it", "we", "they",
    "me", "my", "your", "his", "her", "its", "our", "their", "this", "that", "these",
    "those", "with", "for", "as", "by", "from", "so", "but", "if", "then", "than",
    "what", "who", "when", "where", "how", "all", "any", "our", "us", "do", "does",
    "did", "not", "no", "yes", "oh", "ooh", "ah", "yeah", "la", "na", "ohh",
}

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")

# Extra characters that should be treated as apostrophes.
_APOSTROPHE_SET = set(APOSTROPHES)


def _strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=4096)
def normalize_text(text: str, strip_accents: bool = True) -> str:
    """Return the canonical searchable form of ``text``.

    Cached: pure function, and the same song titles/lyric lines are
    re-normalised on every search without changing.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    lowered = []
    for ch in normalized:
        if ch in _APOSTROPHE_SET:
            continue
        lowered.append(ch.lower() if ch.isalpha() else ch)
    joined = "".join(lowered)
    if strip_accents:
        joined = _strip_diacritics(joined)
    words = _WORD_RE.findall(joined)
    return " ".join(words)


@lru_cache(maxsize=8192)
def normalize_with_map(text: str, strip_accents: bool = True) -> tuple[str, list[int]]:
    """Like :func:`normalize_text` but also returns an index map.

    ``index_map[i]`` is the offset in the *original* string of the character
    that produced ``result[i]``. Used for highlighting.

    Cached: pure function; callers must treat the returned list as
    read-only (every current caller only reads it).
    """
    if not text:
        return "", []
    normalized = unicodedata.normalize("NFKC", str(text))
    chars: list[str] = []
    index_map: list[int] = []
    for index, ch in enumerate(normalized):
        if ch in _APOSTROPHE_SET:
            continue
        if ch.isalpha():
            pieces = _strip_diacritics(ch.lower()) if strip_accents else ch.lower()
        elif ch.isalnum():
            pieces = ch.lower()
        else:
            pieces = " "
        for piece in pieces:
            if piece == " " and (not chars or chars[-1] == " "):
                continue
            chars.append(piece)
            index_map.append(index)

    start = 0
    while start < len(chars) and chars[start] == " ":
        start += 1
    end = len(chars)
    while end > start and chars[end - 1] == " ":
        end -= 1
    return "".join(chars[start:end]), index_map[start:end]


def tokenize(text: str, strip_accents: bool = True) -> list[str]:
    normalized = normalize_text(text, strip_accents=strip_accents)
    return normalized.split() if normalized else []


def content_tokens(tokens: list[str]) -> list[str]:
    """Drop stopwords; fall back to the original list when nothing remains."""
    filtered = [token for token in tokens if token not in STOPWORDS and len(token) > 1]
    return filtered or list(tokens)


def contraction_variants(token: str) -> list[str]:
    """Alternate spellings of a contraction token (``dont`` → ``do not``)."""
    expansion = CONTRACTIONS.get(token)
    if not expansion:
        return []
    return expansion.split()


def like_pattern(query: str) -> str:
    """Build a ``LIKE`` pattern from an already normalized query."""
    cleaned = normalize_text(query)
    if not cleaned:
        return "%"
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def phrase_pattern(query: str) -> str:
    """Substring pattern preserving word order (no wildcards inside)."""
    return like_pattern(query)


@dataclass(frozen=True)
class NormalizedQuery:
    """Parsed representation of one user query."""

    raw: str
    normalized: str
    tokens: tuple[str, ...] = field(default_factory=tuple)
    content: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.normalized

    @property
    def is_generic(self) -> bool:
        """True for very short / stopword-only queries."""
        if not self.content:
            return True
        return len(self.content) == 1 and len(self.content[0]) <= 3

    @property
    def has_signal(self) -> bool:
        return bool(self.tokens)

    @property
    def display(self) -> str:
        return " ".join(self.tokens)


def normalize_query(text: str) -> NormalizedQuery:
    normalized = normalize_text(text)
    tokens = tuple(normalized.split()) if normalized else ()
    content = tuple(content_tokens(list(tokens)))
    return NormalizedQuery(raw=text or "", normalized=normalized, tokens=tokens, content=content)
