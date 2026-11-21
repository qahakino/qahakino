import re

# Turli xil apostroflarni bittaga keltiramiz: o‘, oʻ, o’, o` -> o'
_APOSTROPHES = str.maketrans({c: "'" for c in "’‘ʻʼ`´′"})


def normalize(text: str) -> str:
    text = (text or "").translate(_APOSTROPHES).casefold()
    return re.sub(r"\s+", " ", text).strip()


def matches(query: str, name: str) -> bool:
    """So'rovdagi barcha so'zlar nomning ichida bo'lsa True (tartibi muhim emas)."""
    q = normalize(query)
    if not q:
        return False
    n = normalize(name)
    return all(word in n for word in q.split(" "))
