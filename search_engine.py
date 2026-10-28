"""
Lyric Sync — Offline Gospel Search Engine
Format: .LSDB (SQLite 3.x)
Product: Lyric Sync | Developer: The Kreadive Galaxy

Standalone Python 3 module for offline Gospel song discovery by remembered lyric fragments.
Designed for Windows Desktop integration (OpenCode), Linux, macOS, and embedded environments.
Zero external dependencies required (uses Python standard library: sqlite3, re, math, unicodedata).
"""

import bisect
import sqlite3
import re
import os
import unicodedata
from collections import Counter
from typing import List, Dict, Any, Optional

# Common contraction dictionary for normalization
CONTRACTIONS = {
    "you're": "you are", "youre": "you are",
    "i'm": "i am", "im": "i am",
    "he's": "he is", "hes": "he is",
    "she's": "she is", "shes": "she is",
    "it's": "it is", "its": "it is",
    "we're": "we are", "were": "we are",
    "they're": "they are", "theyre": "they are",
    "i've": "i have", "ive": "i have",
    "we've": "we have", "weve": "we have",
    "you've": "you have", "youve": "you have",
    "they've": "they have", "theyve": "they have",
    "i'll": "i will", "ill": "i will",
    "you'll": "you will", "youll": "you will",
    "don't": "do not", "dont": "do not",
    "doesn't": "does not", "doesnt": "does not",
    "can't": "cannot", "cant": "cannot",
    "won't": "will not", "wont": "will not",
    "that's": "that is", "thats": "that is",
    "what's": "what is", "whats": "what is",
    "there's": "there is", "theres": "there is",
    "'tis": "it is", "tis": "it is",
    "'twas": "it was", "twas": "it was"
}

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'of', 'to', 'in', 'is', 'it',
    'at', 'on', 'for', 'with', 'as', 'by', 'from', 'be', 'are', 'was'
}


def normalize_text(text: str) -> str:
    """Normalizes input text: lowercases, strips accents/punctuation, and expands contractions."""
    if not text:
        return ""
    
    # Unicode NFKD normalization
    text = unicodedata.normalize('NFKD', text)
    text = text.lower()
    
    # Replace curly apostrophes & quotes
    text = re.sub(r"[‘’‛′']", "'", text)
    text = re.sub(r'[“”″"]', '"', text)
    
    # Expand contractions
    tokens = text.split()
    expanded = []
    for t in tokens:
        clean = re.sub(r"[^a-z0-9']", '', t)
        expanded.append(CONTRACTIONS.get(clean, clean))
    
    text = " ".join(expanded)
    
    # Strip non-alphanumeric except space
    text = re.sub(r'[^a-z0-9s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def levenshtein_within(s1: str, s2: str, max_distance: int) -> Optional[int]:
    """Exact Levenshtein distance when it is <= ``max_distance``, else None.

    Banded dynamic programming: cells that cannot belong to a path within the
    budget are clamped to ``max_distance + 1`` and a row whose minimum already
    exceeds the budget aborts early. For every pair whose true distance is
    within the budget the returned value is byte-for-byte identical to
    :func:`levenshtein_distance`; only computations that could never satisfy
    the caller are skipped.
    """
    l1, l2 = len(s1), len(s2)
    if abs(l1 - l2) > max_distance:
        return None
    if l2 == 0:
        return l1 if l1 <= max_distance else None
    previous = list(range(l2 + 1))
    cap = max_distance + 1
    for i in range(1, l1 + 1):
        current = [cap] * (l2 + 1)
        c1 = s1[i - 1]
        current[0] = i if i <= max_distance else cap
        row_min = current[0]
        lo = i - max_distance
        if lo < 1:
            lo = 1
        hi = i + max_distance
        if hi > l2:
            hi = l2
        j = lo
        while j <= hi:
            cost = 0 if c1 == s2[j - 1] else 1
            v = previous[j - 1] + cost
            d = current[j - 1] + 1
            if d < v:
                v = d
            u = previous[j] + 1
            if u < v:
                v = u
            if v > max_distance:
                v = cap
            current[j] = v
            if v < row_min:
                row_min = v
            j += 1
        if row_min > max_distance:
            return None
        previous = current
    result = previous[l2]
    return result if result <= max_distance else None


def match_token_fuzzy(query_token: str, target_token: str) -> tuple[bool, float]:
    """Checks if query_token matches target_token exactly or within allowed edit distance."""
    if query_token == target_token:
        return True, 0.0
    
    if target_token.startswith(query_token) and len(query_token) >= 3:
        return True, 0.1
    
    max_dist = 2 if max(len(query_token), len(target_token)) >= 7 else (1 if max(len(query_token), len(target_token)) >= 4 else 0)
    if max_dist > 0:
        # Edit distance can never be smaller than the length difference, so a
        # cheap bound check skips the full Levenshtein matrix without changing
        # any match decision (identical results, much less work).
        if abs(len(query_token) - len(target_token)) > max_dist:
            return False, 1.0
        # Bounded DP: exact distance when within budget, early abort otherwise
        # — same decisions, a fraction of the work of the full matrix.
        dist = levenshtein_within(query_token, target_token, max_dist)
        if dist is not None:
            return True, dist * 0.25

    return False, 1.0


class LyricSyncSearchEngine:
    """
    Production-quality offline search engine for Lyric Sync .LSDB databases.
    Connects to SQLite, leverages FTS5 and token proximity scoring.
    """

    def __init__(self, lsdb_path: str):
        if not os.path.exists(lsdb_path):
            raise FileNotFoundError(f"LSDB database not found at path: {lsdb_path}")
        self.lsdb_path = lsdb_path
        # check_same_thread=False: the application serialises every access
        # through the search service's lock, while tasks run on the Qt thread
        # pool — the connection legitimately moves between worker threads.
        self.conn = sqlite3.connect(lsdb_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._verify_database()
        # Read-only caches: the .LSDB is never modified by the application, so
        # songs, the search index and their tokenised forms are loaded once
        # instead of on every search (identical data, no repeated reads).
        self._cached_songs: Optional[List[Dict[str, Any]]] = None
        self._cached_index: Dict[Any, str] = {}
        self._cached_token_sets: Dict[Any, set] = {}
        self._cached_vocab: set = set()
        self._vocab_sorted: List[str] = []
        self._vocab_by_len: Dict[int, List[str]] = {}
        self._vocab_counts: Dict[Any, Counter] = {}
        # Query-token -> fuzzy verdicts, persisted across searches (the vocab
        # never changes, verdicts are deterministic), capped to bound memory.
        self._fuzzy_verdict_cache: Dict[str, Dict[str, float]] = {}

    def _verify_database(self):
        """Verifies table presence and integrity."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row['name'] for row in cursor.fetchall()}
        required = {'songs', 'lyrics', 'artists', 'categories', 'database_metadata'}
        missing = required - tables
        if missing:
            raise ValueError(f"Corrupted .LSDB database! Missing tables: {missing}")

    def get_database_info(self) -> Dict[str, Any]:
        """Retrieves manifest metadata from the database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM database_metadata LIMIT 1;")
        row = cursor.fetchone()
        return dict(row) if row else {}

    def search(self, raw_query: str, limit: int = 20, region_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Searches the offline .LSDB database for Gospel songs matching remembered lyric fragments.
        
        Args:
            raw_query: Remembered words, e.g. "mighty God great I am", "when peace like a river"
            limit: Maximum results to return
            region_filter: Optional filter by region (e.g. 'West Africa', 'North America')
            
        Returns:
            List of song records with match scores, confidence ratings, and matched snippets.
        """
        query = normalize_text(raw_query)
        if not query or len(query) < 2:
            return []

        tokens = query.split()
        non_stop_tokens = [t for t in tokens if t not in STOP_WORDS]
        effective_tokens = non_stop_tokens if non_stop_tokens else tokens

        # Songs and index entries are read once and reused: the database is
        # read-only, so repeated searches serve identical data.
        all_songs = self._load_songs(region_filter)
        index_map = self._cached_index
        token_sets = self._cached_token_sets
        lyrics_cursor = self.conn.cursor()

        # Fuzzy verdicts are computed once per query token against the shared
        # token vocabulary instead of once per (song, token) pair. Every song
        # token is in the vocabulary, so each song sees exactly the same
        # match/no-match decisions and penalties as pair-by-pair evaluation.
        # The cache lives on the instance: verdicts only depend on the
        # immutable vocabulary, so repeated queries skip the scan entirely.
        fuzzy_verdicts = self._fuzzy_verdict_cache

        def verdicts_for(q_token: str) -> Dict[str, float]:
            verdicts = fuzzy_verdicts.get(q_token)
            if verdicts is None:
                verdicts = {}
                q_len = len(q_token)
                # match_token_fuzzy branches 1/2 — exact equality (0.0) and
                # query-prefix matches (0.1) — served by one bisect range over
                # the sorted vocabulary instead of a full startswith scan.
                if q_len >= 3:
                    lo = bisect.bisect_left(self._vocab_sorted, q_token)
                    hi = bisect.bisect_right(self._vocab_sorted, q_token + "\uffff")
                    for index in range(lo, hi):
                        candidate = self._vocab_sorted[index]
                        verdicts[candidate] = 0.0 if candidate == q_token else 0.1
                elif q_token in self._cached_vocab:
                    verdicts[q_token] = 0.0
                # Branch 3 — bounded edit distance, evaluated only for
                # length-eligible candidates that share enough characters:
                # distance <= k implies at least len(q) - k characters are
                # shared, so a cheap multiset count proves "cannot match"
                # without running the DP (identical verdicts, far less work).
                q_counts = Counter(q_token)
                for delta in (-2, -1, 0, 1, 2):
                    length = q_len + delta
                    if length < 1:
                        continue
                    longest = max(q_len, length)
                    max_dist = 2 if longest >= 7 else (1 if longest >= 4 else 0)
                    if max_dist == 0 or abs(length - q_len) > max_dist:
                        continue
                    need = q_len - max_dist
                    for candidate in self._vocab_by_len.get(length, ()):
                        if candidate in verdicts:
                            continue
                        if sum((q_counts & self._vocab_counts[candidate]).values()) < need:
                            continue
                        matched, penalty = match_token_fuzzy(q_token, candidate)
                        if matched:
                            verdicts[candidate] = penalty
                if len(fuzzy_verdicts) > 2048:
                    fuzzy_verdicts.clear()
                fuzzy_verdicts[q_token] = verdicts
            return verdicts

        results = []

        for song in all_songs:
            song_id = song['id']
            norm_title = song['normalized_title']
            searchable_text = index_map.get(song_id, '')

            best_score = 0
            exact_match = False
            matched_snippet = None

            # 1. Exact phrase in title
            if norm_title == query or query in norm_title:
                exact_match = True
                best_score = max(best_score, 105 if norm_title == query else 95)
                matched_snippet = song['title']

            # 2. Exact phrase in searchable text (lyrics/aliases/fragments)
            if query in searchable_text:
                exact_match = True
                phrase_bonus = min(40, len(query) * 2)
                best_score = max(best_score, 85 + phrase_bonus)
                matched_snippet = query

            # 3. Token fuzzy overlap & proximity
            searchable_token_set = token_sets.get(song_id, frozenset())
            matched_count = 0
            matched_tokens_list = []
            total_penalty = 0.0

            for q_token in effective_tokens:
                if q_token in searchable_token_set:
                    # Exact token match: penalty 0, same as the loop below
                    # finding it and breaking immediately.
                    matched_count += 1
                    matched_tokens_list.append(q_token)
                    continue
                # Min penalty over this song's tokens that fuzzy-match q_token
                # — identical decision and value to scanning the song's token
                # list with match_token_fuzzy (min is order-independent).
                min_pen = None
                for s_token, pen in verdicts_for(q_token).items():
                    if s_token in searchable_token_set and (
                        min_pen is None or pen < min_pen
                    ):
                        min_pen = pen
                if min_pen is not None:
                    matched_count += 1
                    matched_tokens_list.append(q_token)
                    total_penalty += min_pen

            overlap_ratio = matched_count / len(effective_tokens) if effective_tokens else 0
            
            # Proximity bonus for multi-word matches
            proximity_score = 0
            if len(effective_tokens) > 1 and overlap_ratio >= 0.5:
                proximity_score = overlap_ratio * 30

            token_score = (overlap_ratio * 75) + proximity_score - (total_penalty * 10)
            final_score = min(100, max(best_score, token_score))

            # False positive threshold guard
            if final_score >= 35 and overlap_ratio >= 0.5:
                confidence = 'High' if final_score >= 88 else ('Medium' if final_score >= 70 else 'Low')

                results.append({
                    'song': dict(song),
                    'score': round(final_score),
                    'exact_match': exact_match,
                    'confidence': confidence,
                    'overlap_ratio': round(overlap_ratio, 2),
                    'matched_tokens': matched_tokens_list,
                    'matched_snippet': matched_snippet or (f"Matched: {', '.join(matched_tokens_list)}"),
                    'lyrics': []
                })

        # Sort descending by score; within equal scores exact phrase/title
        # matches come first so the [:limit] cut never discards them in
        # database-insertion order (new rows sort last otherwise).
        results.sort(key=lambda r: (r['score'], r['exact_match']), reverse=True)
        results = results[:limit]

        # Fetch lyric lines only for the songs actually returned (indexed
        # lookup per song); songs beyond the limit would be discarded anyway.
        for item in results:
            if item['song']['copyright_status'] == 'PUBLIC_DOMAIN':
                lyrics_cursor.execute(
                    "SELECT section_type, text FROM lyrics WHERE song_id = ? "
                    "ORDER BY section_order, line_order;",
                    (item['song']['id'],),
                )
                item['lyrics'] = [dict(lr) for lr in lyrics_cursor.fetchall()]
        return results

    def _ensure_caches(self) -> None:
        """Load songs, the search index and tokenised forms once (read-only DB)."""
        if self._cached_songs is not None:
            return
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM songs;")
        songs = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT song_id, searchable_text FROM lyric_search_index;")
        index_map: Dict[Any, str] = {}
        token_sets: Dict[Any, set] = {}
        vocab: set = set()
        for row in cursor.fetchall():
            song_id = row['song_id']
            text = row['searchable_text'] or ''
            index_map[song_id] = text
            tokens = set(text.split())
            token_sets[song_id] = tokens
            vocab.update(tokens)
        self._cached_index = index_map
        self._cached_token_sets = token_sets
        self._cached_vocab = vocab
        # Structures that make the per-query fuzzy verdict scan cheap: a
        # sorted vocabulary for prefix ranges, length buckets for the bounded
        # edit-distance candidates, and per-token character multisets for the
        # sound "cannot match" prefilter. Built once (read-only database).
        self._vocab_sorted = sorted(vocab)
        by_len: Dict[int, List[str]] = {}
        for token in vocab:
            by_len.setdefault(len(token), []).append(token)
        self._vocab_by_len = by_len
        self._vocab_counts = {token: Counter(token) for token in vocab}
        self._cached_songs = songs

    def _load_songs(self, region_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cached ``songs`` rows, optionally filtered by region (same as SQL)."""
        self._ensure_caches()
        assert self._cached_songs is not None
        if region_filter and region_filter != "All":
            return [song for song in self._cached_songs
                    if song.get('region') == region_filter]
        return self._cached_songs

    def close(self):
        """Closes the SQLite database connection."""
        self.conn.close()


# CLI Testing Interface
if __name__ == "__main__":
    import sys
    
    db_file = sys.argv[1] if len(sys.argv) > 1 else "lyric_sync_gospel.lsdb"
    if not os.path.exists(db_file):
        print(f"Error: Database file '{db_file}' not found.")
        sys.exit(1)

    engine = LyricSyncSearchEngine(db_file)
    meta = engine.get_database_info()
    print("=" * 65)
    print(f"Lyric Sync Engine Initialized: {meta.get('database_name', 'lyric_sync_gospel.lsdb')}")
    print(f"Version: {meta.get('database_version', 'N/A')} | Total Songs: {meta.get('total_songs', 'N/A')}")
    print(f"Checksum: {meta.get('sha256_checksum', 'N/A')}")
    print("=" * 65)

    test_queries = [
        "mighty God great I am",
        "mighty god graet",
        "running after me all my life",
        "when peace like a river",
        "break every chain army rising"
    ]

    for q in test_queries:
        print(f"\nSearch Query: '{q}'")
        res = engine.search(q, limit=3)
        for idx, item in enumerate(res, 1):
            s = item['song']
            print(f"  #{idx} [{item['score']}% - {item['confidence']}] {s['title']} — {s['artist']} ({s['country']}) [{s['copyright_status']}]")
            if item.get('matched_snippet'):
                print(f"      Snippet: \"{item['matched_snippet']}\"")

    engine.close()