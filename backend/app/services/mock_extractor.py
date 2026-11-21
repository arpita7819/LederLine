"""Deterministic keyword extractor used in Demo Mode (no API key). Pure stdlib."""
import re

from .dates import find_date_phrase

Q = "['’]"
FILLER = re.compile(r"^(?:(?:okay|ok|sure|yes|yeah|yep|great|alright|right|so|and|well|then|also)\b[,.]?\s+)+", re.I)
DECISION = re.compile(
    rf"\b(?:we(?:{Q}ve| have)?\s+(?:decided|agreed)|we(?:{Q}ll| will|{Q}re| are)\s+"
    rf"(?:going\s+with|go\s+with|use|using|switch(?:ing)?\s+to|mov(?:e|ing)\s+to|adopt(?:ing)?)|"
    rf"let{Q}?s\s+(?:go\s+with|use|switch\s+to|move\s+to|adopt)|the decision is|final call|going with)\b"
    r"|decision:", re.I)
STRONG = re.compile(r"decided|agreed|decision|final call", re.I)
SELF = re.compile(rf"\b(?:i{Q}ll|i will|i{Q}m going to|i can take)\b", re.I)
ASK = re.compile(r"\b(?:can|could|will|would) you\b", re.I)
GENERIC = re.compile(r"\baction item\b|\b(?:needs?|has|have) to\b", re.I)


def _clean(sent: str, names: str) -> str:
    t = FILLER.sub("", sent).strip()
    t = re.sub(rf"^(?:{names})\s+(?:will|{Q}ll|is going to|to|needs to|should|has to)\s+", "", t, flags=re.I)
    t = re.sub(rf"^(?:{names})\b[,:]?\s+", "", t)
    t = re.sub(rf"^(?:(?:can|could|will|would)\s+you\s+|i{Q}ll\s+|i will\s+|i{Q}m going to\s+|i can take\s+)", "", t, flags=re.I)
    t = t.rstrip(".!? ")
    t = re.sub(rf",\s*(?:{names})$", "", t)
    return t[:1].upper() + t[1:]


def mock_extract(utterances: list[dict], known_names: list[str]) -> dict:
    """utterances: [{idx, speaker, text}]. Returns a dict matching extract_schema.json."""
    full = {n.split()[0].casefold(): n for n in known_names if n.strip()}
    names = "|".join(re.escape(k.title()) for k in full) or "(?!)"
    will = re.compile(rf"\b({names})\s+(?:will|{Q}ll|is going to)\b")
    decisions, actions = [], []
    for u in utterances:
        for sent in re.split(r"(?<=[.!?])\s+", u["text"].strip()):
            sent = sent.strip()
            if not sent:
                continue
            if DECISION.search(sent):
                text = _clean(sent, names)
                if len(text.split()) >= 2:
                    decisions.append({"text": text, "quote": sent, "utterance_index": u["idx"],
                                      "confidence": 0.9 if STRONG.search(sent) else 0.78})
                continue
            owner = None
            named = re.search(rf"\b({names})\b", sent)
            if SELF.search(sent):
                owner = u["speaker"]
            elif (m := will.search(sent)):
                owner = full[m.group(1).casefold()]
            elif ASK.search(sent) and named and full[named.group(1).casefold()] != u["speaker"]:
                owner = full[named.group(1).casefold()]
            elif GENERIC.search(sent):
                owner = full[named.group(1).casefold()] if named else None
            else:
                continue
            title = _clean(sent, names)
            words = title.split()
            if len(words) < 3 or (re.search(r"\b(it|that|this|them)\b", title, re.I) and len(words) <= 5):
                continue
            deadline = find_date_phrase(sent)
            conf = 0.85 - (0.15 if not owner else 0) - (0.1 if not deadline else 0)
            actions.append({"title": title, "quote": sent, "utterance_index": u["idx"],
                            "confidence": round(conf, 2), "owner": owner, "deadline_text": deadline})
    return {"decisions": decisions, "action_items": actions}
