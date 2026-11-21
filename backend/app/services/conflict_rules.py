"""Stdlib-only retrieval scoring and the demo-mode conflict classifier."""
import re

STOP = set("""the and for that this with are was were will have has had not but you your our from they them
there their what when where which who why how can could should would about into over then than also just
let lets going gonna need needs use using""".split())

TOPICS = {
    "database": ["postgresql", "postgres", "mysql", "mariadb", "mongodb", "sqlite", "dynamodb", "cassandra"],
    "cloud": ["aws", "gcp", "azure", "vercel", "heroku"],
    "billing": ["stripe", "paddle", "braintree"],
    "backend language": ["python", "java", "golang", "rust", "node.js", "nodejs", "ruby"],
    "frontend framework": ["react", "vue", "angular", "svelte"],
    "tracker": ["jira", "linear", "asana"],
}
ALIASES = {"postgres": "postgresql", "nodejs": "node.js"}
SUPERSEDE_CUE = re.compile(r"\b(supersed\w*|replac\w*|overrid\w*|instead of|no longer|scrap\w*|revers\w*|rather than)\b", re.I)
MIN_SCORE = 0.2


def keywords(text: str, limit: int = 12) -> list[str]:
    out: list[str] = []
    for w in re.findall(r"[a-z0-9+#.]{3,}", text.lower()):
        w = w.strip(".")
        if w and w not in STOP and w not in out:
            out.append(w)
    return out[:limit]


def topics_of(text: str) -> dict[str, set[str]]:
    """Every known option mentioned, grouped by topic (a sentence can name both old and new)."""
    found: dict[str, set[str]] = {}
    for topic, techs in TOPICS.items():
        for t in techs:
            if re.search(rf"(?<![\w.]){re.escape(t)}(?![\w])", text, re.I):
                found.setdefault(topic, set()).add(ALIASES.get(t, t))
    return found


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def retrieval_score(new_kw, new_text, old_kw, old_text) -> float:
    shared = set(topics_of(new_text)) & set(topics_of(old_text))
    return round(jaccard(new_kw, old_kw) + (0.3 if shared else 0.0), 3)


def mock_classify(new_text: str, old_text: str) -> tuple[str, str]:
    nt, ot = topics_of(new_text), topics_of(old_text)
    shared = [t for t in nt if t in ot]
    for t in shared:
        fresh = nt[t] - ot[t]  # an option the earlier decision did not choose
        if fresh:
            verdict = "supersedes" if SUPERSEDE_CUE.search(new_text) else "contradicts"
            return verdict, (f"The new decision picks {sorted(fresh)[0]} for the {t}, "
                             f"but the earlier decision chose {sorted(ot[t])[0]}.")
    if shared:
        return "consistent", f"Both decisions choose {sorted(nt[shared[0]])[0]} for the {shared[0]}."
    if jaccard(keywords(new_text), keywords(old_text)) >= 0.5:
        return "consistent", "The two decisions cover the same ground and agree."
    return "unrelated", ""
