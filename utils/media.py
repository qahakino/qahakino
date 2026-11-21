import asyncio
import logging
import shutil
from pathlib import Path

from config import BG_VOLUME, VOICE_LUFS


class MediaError(Exception):
    """ffmpeg/ffprobe bilan ishlashdagi xatolik."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


async def _run(*args: str, timeout: int) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaError("ffmpeg juda uzoq ishladi (timeout).")
    return proc.returncode, out, err


async def probe_duration(path: Path) -> float:
    """Fayl davomiyligi (soniya)."""
    code, out, err = await _run(
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
        timeout=30,
    )
    if code != 0:
        raise MediaError(f"ffprobe xatosi: {err.decode(errors='ignore')[-300:]}")
    try:
        return float(out.decode().strip())
    except ValueError:
        raise MediaError("Fayl davomiyligini aniqlab bo'lmadi.")


async def replace_audio(video: Path, voice: Path, output: Path, timeout: int = 240) -> None:
    """
    Videodagi ovozni foydalanuvchi ovozi bilan almashtiradi.

    - Video qayta kodlanmaydi (-c:v copy), shuning uchun juda tez.
    - Ovoz videodan qisqa bo'lsa, oxiri sukunat bilan to'ldiriladi (apad),
      ya'ni video to'liq ijro bo'ladi.
    - Copy ishlamasa (g'alati kodek), libx264 bilan qayta kodlab ko'riladi.
    """
    base = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(voice),
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]
    audio = [
        "-c:a", "aac", "-b:a", "128k",
        "-af", f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11,aresample=44100,apad",
    ]
    tail = ["-shortest", "-movflags", "+faststart", str(output)]

    code, _, err = await _run(*base, "-c:v", "copy", *audio, *tail, timeout=timeout)
    if code == 0 and output.exists() and output.stat().st_size > 0:
        return

    logging.warning("ffmpeg copy ishlamadi, qayta kodlab ko'ramiz: %s",
                    err.decode(errors="ignore")[-300:])

    code, _, err = await _run(
        *base,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p",
        *audio, *tail,
        timeout=timeout,
    )
    if code != 0 or not output.exists() or output.stat().st_size == 0:
        raise MediaError(f"ffmpeg xatosi: {err.decode(errors='ignore')[-300:]}")


async def has_audio_stream(path: Path) -> bool:
    code, out, _ = await _run(
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
        timeout=30,
    )
    return code == 0 and bool(out.decode().strip())


async def mix_parts(
    video: Path,
    voices: list[tuple[Path, float]],
    output: Path,
    bg_volume: float = BG_VOLUME,
    timeout: int = 300,
) -> None:
    """
    Orqa fonli video ustiga bir nechta ovozni o'z vaqtida qo'yadi.

    voices: [(ovoz_fayli, boshlanish_soniyasi), ...]
    - Video qayta kodlanmaydi (copy) — tez.
    - Orqa fon musiqasi saqlanadi, ovozlar uning ustida eshitiladi.
    - Videoda ovoz yo'q bo'lsa, sukunat ustiga qo'yiladi.
    """
    total = await probe_duration(video)
    with_audio = await has_audio_stream(video)

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    chains: list[str] = []

    if with_audio:
        chains.append(f"[0:a]{fmt},volume={bg_volume},apad[bg]")
    else:
        chains.append(f"anullsrc=r=44100:cl=stereo,{fmt}[bg]")

    labels = ["[bg]"]
    for i, (_path, start) in enumerate(voices, start=1):
        delay = int(round(start * 1000))
        chains.append(
            # loudnorm: past yozilgan ovozni ham bir xil balandlikka ko'taradi
            # (u ichida 192 kHz ga o'tadi, shuning uchun keyin qayta 44.1 kHz)
            f"[{i}:a]loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11,{fmt},"
            f"adelay={delay}|{delay},apad[v{i}]"
        )
        labels.append(f"[v{i}]")

    k = len(labels)
    # Barcha kirishlar apad bilan "cheksiz" qilingani uchun amix hammasini oxirigacha
    # faol tutadi; hajm 1/k ga kamayadi, volume=k bilan qaytaramiz.
    chains.append(
        f"{''.join(labels)}amix=inputs={k}:duration=first:dropout_transition=0,"
        f"volume={k},alimiter=limit=0.95[aout]"
    )

    base = ["ffmpeg", "-y", "-i", str(video)]
    for path, _start in voices:
        base += ["-i", str(path)]
    base += [
        "-filter_complex", ";".join(chains),
        "-map", "0:v:0", "-map", "[aout]",
    ]
    audio = ["-c:a", "aac", "-b:a", "160k"]
    tail = ["-t", f"{total:.3f}", "-movflags", "+faststart", str(output)]

    code, _, err = await _run(*base, "-c:v", "copy", *audio, *tail, timeout=timeout)
    if code == 0 and output.exists() and output.stat().st_size > 0:
        return

    logging.warning("mix_parts: copy ishlamadi, qayta kodlab ko'ramiz: %s",
                    err.decode(errors="ignore")[-400:])

    code, _, err = await _run(
        *base,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
        *audio, *tail,
        timeout=timeout,
    )
    if code != 0 or not output.exists() or output.stat().st_size == 0:
        raise MediaError(f"ffmpeg xatosi: {err.decode(errors='ignore')[-400:]}")
