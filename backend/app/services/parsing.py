"""Transcript parsing for plain text, WebVTT and SRT."""
import re
from dataclasses import dataclass
from typing import Optional

TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
NAME = r"[^\W\d_][\w .'’\-]{0,38}"

LEAD_TS = re.compile(rf"^[\[(]?(?P<ts>{TS})[\])]?\s*[-–—]?\s*")
SPEAKER_LINE = re.compile(
    rf"^(?P<sp>{NAME}?)(?:\s*[\[(](?P<ts>{TS})[\])])?\s*:\s*(?P<text>.*)$"
)
CUE_TIME = re.compile(rf"(?P<start>{TS})\s*-->\s*(?P<end>{TS})")
VOICE_TAG = re.compile(r"<v(?:\.[\w-]+)*\s+(?P<sp>[^>]+)>")
ANY_TAG = re.compile(r"</?[^>]+>")


@dataclass
class ParsedUtterance:
    speaker: str
    text: str
    timestamp: Optional[float] = None


def ts_to_seconds(ts: str) -> float:
    total = 0.0
    for part in ts.replace(",", ".").split(":"):
        total = total * 60 + float(part)
    return total


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def detect_format(text: str) -> str:
    head = text.lstrip("\ufeff \t\r\n")
    if head.startswith("WEBVTT"):
        return "vtt"
    if re.search(r"^\d+\s*\n\s*" + TS + r"\s*-->", head, re.M) and "," in (
        CUE_TIME.search(head).group(0) if CUE_TIME.search(head) else ""
    ):
        return "srt"
    return "txt"


def _parse_line(line: str, default_ts: Optional[float] = None):
    """Return (speaker|None, text, ts) for one transcript line."""
    line = line.strip()
    ts = default_ts
    m = LEAD_TS.match(line)
    if m:
        ts = ts_to_seconds(m.group("ts"))
        line = line[m.end():]
    v = VOICE_TAG.match(line)
    if v:
        return clean_name(v.group("sp")), ANY_TAG.sub("", line[v.end():]).strip(), ts
    line = ANY_TAG.sub("", line)
    s = SPEAKER_LINE.match(line)
    if s:
        if s.group("ts"):
            ts = ts_to_seconds(s.group("ts"))
        return clean_name(s.group("sp")), s.group("text").strip(), ts
    return None, line.strip(), ts


def _parse_plain(text: str) -> list[ParsedUtterance]:
    out: list[ParsedUtterance] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        speaker, body, ts = _parse_line(raw)
        if speaker:
            out.append(ParsedUtterance(speaker, body, ts))
        elif out and body:  # continuation of the previous speaker's turn
            out[-1].text = f"{out[-1].text} {body}".strip()
        elif body:
            out.append(ParsedUtterance("Unknown", body, ts))
    return [u for u in out if u.text]


def _parse_cues(text: str) -> list[ParsedUtterance]:
    out: list[ParsedUtterance] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = block.strip().split("\n")
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue  # header, NOTE or STYLE block
        cue = CUE_TIME.search(lines[idx])
        if not cue:
            continue
        start = ts_to_seconds(cue.group("start"))
        first = True
        for line in lines[idx + 1:]:
            if not line.strip():
                continue
            speaker, body, ts = _parse_line(line, default_ts=start)
            if not body:
                continue
            if speaker:
                out.append(ParsedUtterance(speaker, body, start if first else ts))
            elif out:
                out[-1].text = f"{out[-1].text} {body}".strip()
            else:
                out.append(ParsedUtterance("Unknown", body, start))
            first = False
    return out


def parse_transcript(text: str) -> tuple[str, list[ParsedUtterance]]:
    """Return (format, utterances). Consecutive turns by one speaker stay separate."""
    text = text.lstrip("\ufeff")
    fmt = detect_format(text)
    utterances = _parse_cues(text) if fmt in ("vtt", "srt") else _parse_plain(text)
    return fmt, utterances
