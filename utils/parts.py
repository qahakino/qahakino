import re

from config import MAX_CLIP_PARTS

_TIME = r"(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
LINE_RE = re.compile(rf"^\s*{_TIME}\s*[-–—]\s*{_TIME}\s*\|\s*(.+?)\s*$")


def _to_seconds(minutes: str, seconds: str, frac: str | None) -> float | None:
    sec = int(seconds)
    if sec >= 60:
        return None
    value = int(minutes) * 60 + sec
    if frac:
        value += float("0." + frac)
    return float(value)


def fmt_time(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_parts(
    text: str, max_duration: float | None = None
) -> tuple[list[dict], list[str]]:
    """
    Admin yuborgan matnni qismlarga ajratadi.

    Har bir qator:   MM:SS-MM:SS | matn
    Qaytaradi: (qismlar, xatolar). Xato bo'lsa qismlar ishlatilmaydi.
    """
    parts: list[dict] = []
    errors: list[str] = []
    prev_end = 0.0

    lines = [ln for ln in (text or "").splitlines() if ln.strip()]

    for number, raw in enumerate(lines, start=1):
        m = LINE_RE.match(raw)
        if not m:
            errors.append(f"{number}-qator: format noto'g'ri — «{raw.strip()[:40]}»")
            continue

        start = _to_seconds(m.group(1), m.group(2), m.group(3))
        end = _to_seconds(m.group(4), m.group(5), m.group(6))
        body = m.group(7).strip()

        if start is None or end is None:
            errors.append(f"{number}-qator: soniya 00 dan 59 gacha bo'lishi kerak.")
            continue
        if end - start < 1:
            errors.append(f"{number}-qator: tugash vaqti boshlanishdan kamida 1 soniya keyin bo'lsin.")
            continue
        if start < prev_end - 0.05:
            errors.append(f"{number}-qator: oldingi qism bilan kesishadi yoki tartibi noto'g'ri.")
            continue
        if max_duration and end > max_duration + 1:
            errors.append(
                f"{number}-qator: tugash vaqti ({fmt_time(end)}) videodan "
                f"({fmt_time(max_duration)}) uzun."
            )
            continue

        parts.append({"start": start, "end": end, "text": body})
        prev_end = end

    if not lines:
        errors.append("Hech qanday qism topilmadi.")
    if len(parts) > MAX_CLIP_PARTS:
        errors.append(f"Qismlar juda ko'p (ko'pi bilan {MAX_CLIP_PARTS} ta).")

    return parts, errors
