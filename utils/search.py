import re

# Turli xil apostroflarni bittaga keltiramiz: o‘, oʻ, o’, o` -> o'
_APOSTROPHES = str.maketrans({c: "'" for c in "’‘ʻʼ`´′"})

# Kirill -> lotin (o'zbek lotin imlosiga yaqin). Qidiruvda so'rov ham, nom ham
# shu bir xil shaklga keltiriladi, shuning uchun «Темир одам» = «Temir odam».
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "ң": "ng",
}
_VOWELS = "аеёиоуыэюяў"


def _translit(text: str) -> str:
    out, prev = [], " "
    for ch in text:
        if ch == "е" and (prev == " " or prev in _VOWELS or prev in "ъь"):
            out.append("ye")          # Етти -> yetti, Елена -> yelena, Мария -> mariya
        else:
            out.append(_CYR.get(ch, ch))
        prev = ch
    return "".join(out)


def normalize(text: str) -> str:
    """Qidiruv uchun yagona shakl: kichik harf, lotin, apostrofsiz.

    «Темир одам», «Temir odam», «TEMIR ODAM» va «Qo'rqinchli» = «qorqinchli»
    bir xil shaklga keladi.
    """
    text = (text or "").translate(_APOSTROPHES).casefold()
    text = _translit(text)
    text = text.replace("'", "")
    return re.sub(r"\s+", " ", text).strip()


def matches(query: str, name: str) -> bool:
    """So'rovdagi barcha so'zlar nomning ichida bo'lsa True (tartibi muhim emas)."""
    q = normalize(query)
    if not q:
        return False
    n = normalize(name)
    return all(word in n for word in q.split(" "))


def split_aliases(aliases) -> list[str]:
    """Qo'shimcha nomlar: vergul, nuqta-vergul yoki yangi qator bilan ajratilgan."""
    return [a.strip() for a in re.split(r"[,;\n]", aliases or "") if a.strip()]


def item_matches(query: str, name: str, aliases=None) -> bool:
    """Nom yoki qo'shimcha nomlardan (ruscha, inglizcha, asl nom) biri mos kelsa True."""
    return matches(query, name or "") or any(matches(query, a) for a in split_aliases(aliases))


def tokens_match(a: str, b: str) -> bool:
    """a dagi barcha so'zlar b da (to'liq so'z sifatida) bor — buyurtma nomini kino nomiga
    taqqoslash uchun (so'z bo'lagi emas, to'liq so'z)."""
    ta, tb = normalize(a).split(), set(normalize(b).split())
    return bool(ta) and all(w in tb for w in ta)
