"""Document text helpers shared by summaries and debates."""
import hashlib
import re
import unicodedata


def fingerprint(draft):
    return hashlib.sha256(draft["document"].encode()).hexdigest()


def source_quote(quote, source, limit=1000):
    """Recover a literal PDF span after harmless model formatting changes."""
    compact = []
    offsets = []
    for index, char in enumerate(source):
        for normalized in unicodedata.normalize("NFKC", char):
            if not normalized.isspace():
                compact.append(normalized)
                offsets.append(index)
    searchable = "".join(compact)
    formatted = quote.replace("\\n", "\n").replace("\\t", "\t")
    # A model sometimes substitutes a circled list number. Omit only that
    # leading marker; the remaining wording must still match the source.
    without_marker = re.sub(r"^\s*(?:[①-⑳]|[0-9]{1,2}[.)]?)\s*", "", formatted)
    for candidate in dict.fromkeys([quote, formatted, without_marker]):
        if candidate in source and len(candidate) <= limit:
            return candidate
        needle = "".join(char for char in unicodedata.normalize("NFKC", candidate) if not char.isspace())
        if len(needle) < 12:
            continue
        start = searchable.find(needle)
        if start < 0:
            continue
        recovered = source[offsets[start]:offsets[start + len(needle) - 1] + 1]
        if len(recovered) <= limit:
            return recovered
    return None
