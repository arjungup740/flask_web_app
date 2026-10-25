"""Step 4: word-level language shares per song.

Two taggers ("backends") label every word of every song:
  claude  Claude Opus 5.5 reads the whole song and returns one label per word
          (needs ANTHROPIC_API_KEY).
  jev     TypeSafe's Jev answers one multiple-choice question per word, with a probability for
          every language and a confidence (needs TYPESAFE_API_KEY).

  python tag_languages.py tag [--backend claude|jev] [--force] ["Song title" ...]
      Tags every song that has lyrics (or just the titles given) and isn't tagged yet by that
      backend; --force re-tags. Writes data/language_tags/input/<NN_film>__<NN_song>.txt (the
      numbered lines) and data/language_tags/output_<backend>/<same name>.json.
  python tag_languages.py summarize [--backend claude|jev]
      Writes data/song_languages.csv (claude) or data/song_languages_jev.csv (jev).
  python tag_languages.py compare
      Word-by-word agreement between the two backends on songs both have tagged
      → data/tagger_comparison.csv.
  python tag_languages.py prepare "Song title" ...
      Only writes the input files, e.g. to inspect what would be sent.

The tagging rules are in language_tagging_guidelines.md (sent whole to Claude; condensed into
the Jev answer options below). The lyrics used are the original script when available, else
romanized. Percentages count every word as sung (choruses included); vocables and names are
left out of the denominator. For original-script songs it also reports the share of lines (and
words) written in Gurmukhi vs Devanagari, which doesn't depend on either tagger.
"""
import argparse
import csv
import json
import random
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scrape_films import DATA_DIR
from scrape_lyrics import SCRIPT_RANGES

TAG_DIR = DATA_DIR / "language_tags"
GUIDELINES = Path(__file__).parent / "language_tagging_guidelines.md"
CLAUDE_MODEL = "claude-opus-5-5"
JEV_MODEL = "jev-1.14.0"  # pinned rather than jev-latest, so confidences stay comparable across runs
TOKEN = re.compile(r"[\wऀ-෿؀-ۿ'’]+(?:-[\wऀ-෿؀-ۿ'’]+)*")
OTHER_LANGUAGES = ["Haryanvi", "Bhojpuri", "Rajasthani", "Marathi", "Sanskrit", "Persian", "Arabic", "Spanish", "Other"]
LABELS = ["hindi_urdu", "punjabi", "english", "vocable", "name"] + [f"other:{l}" for l in OTHER_LANGUAGES]
EXCLUDED = {"vocable", "name"}
MAX_ATTEMPTS = 3
LOW_CONFIDENCE = 0.5

# Jev reads each option's description, so these carry the guidelines' rules in short form.
JEV_CRITERIA = {
    "hindi_urdu": "Hindi or Urdu. Also a word that Hindi and Punjabi share (dil, yaar, ishq, main, tu, mera) "
                  "when its phrase has no Punjabi grammar, and sargam syllables (sa re ga ma pa dha ni).",
    "punjabi": "Punjabi: a Punjabi word form (ni, ve, tenu, menu, sanu, vich, naal, da/di/de as possessives, "
               "kudi, hoya, kardi, ae for hai, -eya/-iya forms like chaleya or chhodiya), or a shared word "
               "inside a phrase whose grammar is Punjabi.",
    "english": "An English word, in any script (party, selfie, t-shirt).",
    "vocable": "A non-lexical sound or filler (oh, ho, aa, hey, yeah, la la, na na, humming), or junk text.",
    "name": "A proper noun: a person, place, deity, or film title.",
    **{f"other:{l}": f"{l}." for l in OTHER_LANGUAGES if l != "Other"},
    "other:Other": "Another language not listed here.",
}
JEV_BATCH = 80  # words per Jev request; each request repeats the whole song as state

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string", "enum": LABELS}},
                },
                "required": ["line", "labels"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["lines", "notes"],
    "additionalProperties": False,
}


def output_dir(backend):
    return TAG_DIR / f"output_{backend}"


def token_script(text):
    counts = Counter()
    for ch in text:
        if ch.isascii() and ch.isalpha():
            counts["Latin"] += 1
        for name, (lo, hi) in SCRIPT_RANGES.items():
            if lo <= ord(ch) <= hi:
                counts[name] += 1
    return counts.most_common(1)[0][0] if counts else None


def load_songs():
    with open(DATA_DIR / "lyrics_coverage.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["original_file"] or r["romanized_file"]]


def song_key(row):
    path = Path(row["original_file"] or row["romanized_file"])
    return f"{path.parent.name}__{path.name.split('.')[0]}"


def tokenized_lines(row):
    text_used = "original" if row["original_file"] else "romanized"
    text = (DATA_DIR / row[f"{text_used}_file"]).read_text(encoding="utf-8")
    lines = [TOKEN.findall(line) for line in text.splitlines()]
    return text_used, [tokens for tokens in lines if tokens]


def write_input(row):
    """The numbered lines sent to the tagger; '[n]' is the token count the labels must match."""
    text_used, lines = tokenized_lines(row)
    body = "\n".join(f"L{i} [{len(t)}]: {' '.join(t)}" for i, t in enumerate(lines, 1))
    text = f"# {row['film']} / {row['title']} ({text_used} text, {len(lines)} lines)\n{body}\n"
    (TAG_DIR / "input").mkdir(parents=True, exist_ok=True)
    (TAG_DIR / "input" / f"{song_key(row)}.txt").write_text(text, encoding="utf-8")
    return text, lines


def count_mismatches(labels, lines):
    return [f"L{i} needs {len(t)} labels, got {len(labels.get(f'L{i}', []))}"
            for i, t in enumerate(lines, 1) if len(labels.get(f"L{i}", [])) != len(t)]


def save_tags(row, backend, tags):
    output_dir(backend).mkdir(parents=True, exist_ok=True)
    (output_dir(backend) / f"{song_key(row)}.json").write_text(
        json.dumps(tags, ensure_ascii=False, indent=1), encoding="utf-8")


def tag_song_claude(client, row):
    import anthropic

    text, lines = write_input(row)
    prompt = "Tag every token of this song.\n\n" + text
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with client.beta.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=64000,
                system=GUIDELINES.read_text(encoding="utf-8"),
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "high",
                               "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # re-run on a fallback model if a safety classifier declines
            ) as stream:
                response = stream.get_final_message()
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            return f"{row['title']}: API error, not tagged ({exc})"

        if response.stop_reason == "refusal":
            return f"{row['title']}: declined by the model, not tagged"
        if response.stop_reason == "max_tokens":
            return f"{row['title']}: response cut off at max_tokens, not tagged"
        result = json.loads(next(b.text for b in response.content if b.type == "text"))
        labels = {entry["line"]: entry["labels"] for entry in result["lines"]}
        mismatches = count_mismatches(labels, lines)
        if not mismatches or attempt == MAX_ATTEMPTS:
            break
        prompt = ("Tag every token of this song. A previous attempt got these label counts wrong, "
                  "so match each line's [n] exactly: " + "; ".join(mismatches) + "\n\n" + text)

    save_tags(row, "claude", {"labels": labels, "notes": result["notes"], "model": CLAUDE_MODEL})
    warning = f" (still {len(mismatches)} mismatched lines, left out of the shares)" if mismatches else ""
    return f"{row['title']}: tagged{warning}"


def jev_question(lines, i, j):
    from typesafe_sdk import Choice

    marked = " ".join(f"[[{t}]]" if k == j else t for k, t in enumerate(lines[i - 1]))
    options = list(JEV_CRITERIA)
    # Jev leans toward the first option listed, so each word gets its own (reproducible) order.
    random.Random(f"L{i}_w{j}").shuffle(options)
    return Choice(
        instructions=(f"Line L{i} of the song in `lines` is: {marked}\n"
                      f"What language is the word in double brackets, \"{lines[i - 1][j]}\"? "
                      "Judge it in the context of its phrase: a word Hindi and Punjabi share takes the "
                      "language of the phrase it is in. Script is evidence, not the answer."),
        criteria={o: JEV_CRITERIA[o] for o in options},
    )


def tag_song_jev(client, row):
    from typesafe_sdk import TypeSafeError

    _, lines = write_input(row)
    state = {"song": f"{row['film']} / {row['title']}",
             "lines": {f"L{i}": " ".join(t) for i, t in enumerate(lines, 1)}}
    words = [(i, j) for i, tokens in enumerate(lines, 1) for j in range(len(tokens))]
    answers, model, batch, start = {}, JEV_MODEL, JEV_BATCH, 0
    while start < len(words):
        chunk = words[start:start + batch]
        try:
            response = client.system_one(
                state, {f"L{i}_w{j}": jev_question(lines, i, j) for i, j in chunk}, model=JEV_MODEL)
        except TypeSafeError as exc:
            if "max_tokens_exceeded" in str(exc) and batch > 5:
                batch //= 2  # request over the context limit: retry this chunk in smaller pieces
                continue
            return f"{row['title']}: API error, not tagged ({exc})"
        answers.update(response.choices)
        model = response.model
        start += len(chunk)

    labels, probabilities, confidence = {}, {}, {}
    for i, tokens in enumerate(lines, 1):
        line_answers = [answers[f"L{i}_w{j}"] for j in range(len(tokens))]
        labels[f"L{i}"] = [a.choice for a in line_answers]
        probabilities[f"L{i}"] = [{k: round(v, 4) for k, v in a.probabilities.items()} for a in line_answers]
        confidence[f"L{i}"] = [round(a.confidence, 4) for a in line_answers]
    save_tags(row, "jev", {"labels": labels, "probabilities": probabilities, "confidence": confidence,
                           "model": model})
    return f"{row['title']}: tagged ({len(words)} words)"


def tag(backend, titles, force, workers):
    songs = load_songs()
    if titles:
        songs = [r for r in songs if r["title"] in titles]
        missing = set(titles) - {r["title"] for r in songs}
        if missing:
            raise SystemExit(f"no lyrics for: {', '.join(sorted(missing))}")
    if not force:
        songs = [r for r in songs if not (output_dir(backend) / f"{song_key(r)}.json").exists()]

    if backend == "claude":
        import anthropic
        client, tag_song, model = anthropic.Anthropic(max_retries=5), tag_song_claude, CLAUDE_MODEL
    else:
        from typesafe_sdk import TypeSafeClient
        client, tag_song, model = TypeSafeClient(), tag_song_jev, JEV_MODEL
    print(f"tagging {len(songs)} songs with {model}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for message in pool.map(lambda r: tag_song(client, r), songs):
            print(message)


def language_group(label):
    return "other" if label.startswith("other:") else label


def summarize(backend):
    out = []
    for row in load_songs():
        tag_file = output_dir(backend) / f"{song_key(row)}.json"
        if not tag_file.exists():
            continue
        text_used, lines = tokenized_lines(row)
        tags = json.loads(tag_file.read_text(encoding="utf-8"))

        labels, soft, other_langs, low_confidence = Counter(), Counter(), Counter(), 0
        mismatched = [f"L{i}" for i, t in enumerate(lines, 1) if len(tags["labels"].get(f"L{i}", [])) != len(t)]
        for i, tokens in enumerate(lines, 1):
            line = f"L{i}"
            if line in mismatched:
                continue
            for label in tags["labels"][line]:
                if label.startswith("other:"):
                    other_langs[label.split(":", 1)[1]] += 1
                labels[language_group(label)] += 1
            for probs in tags.get("probabilities", {}).get(line, []):
                for label, p in probs.items():
                    soft[language_group(label)] += p
            low_confidence += sum(c < LOW_CONFIDENCE for c in tags.get("confidence", {}).get(line, []))
        if mismatched:
            print(f"warning: {row['title']}: label count != token count on {', '.join(mismatched)}; "
                  "those lines are left out")

        words = sum(n for label, n in labels.items() if label not in EXCLUDED)
        pct = lambda n, d: round(100 * n / d, 1) if d else ""
        result = {
            "film": row["film"], "title": row["title"], "text_used": text_used,
            "words": words,
            "pct_hindi_urdu": pct(labels["hindi_urdu"], words),
            "pct_punjabi": pct(labels["punjabi"], words),
            "pct_english": pct(labels["english"], words),
            "pct_other": pct(labels["other"], words),
            "other_languages": "; ".join(f"{k} {v}" for k, v in other_langs.most_common()),
            "vocables_and_names": labels["vocable"] + labels["name"],
            "lines_left_out": len(mismatched),
        }
        if soft:
            # Probability-weighted shares: a word that is 90% Punjabi counts as 0.9 of a Punjabi word.
            soft_words = sum(p for label, p in soft.items() if label not in EXCLUDED)
            for lang in ("hindi_urdu", "punjabi", "english", "other"):
                result[f"soft_pct_{lang}"] = pct(soft[lang], soft_words)
            result["low_confidence_words"] = low_confidence
        if text_used == "original":
            # Script share, independent of the tagger: lines (and words) written in Gurmukhi vs Devanagari.
            line_scripts = Counter(token_script(" ".join(t)) for t in lines)
            tok_scripts = Counter(token_script(t) for tokens in lines for t in tokens)
            result["pct_lines_gurmukhi"] = pct(line_scripts["Gurmukhi"], line_scripts["Gurmukhi"] + line_scripts["Devanagari"])
            result["pct_words_gurmukhi"] = pct(tok_scripts["Gurmukhi"], tok_scripts["Gurmukhi"] + tok_scripts["Devanagari"])
        out.append(result)

    if not out:
        raise SystemExit(f"no songs tagged by {backend} yet; run `tag --backend {backend}` first")
    path = DATA_DIR / ("song_languages.csv" if backend == "claude" else f"song_languages_{backend}.csv")
    fields = list(dict.fromkeys(k for r in out for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote {path.relative_to(DATA_DIR.parent)} ({len(out)} songs)")


def compare():
    """Word-by-word agreement between Claude's labels and Jev's top choice."""
    out, disagreements = [], Counter()
    for row in load_songs():
        files = [output_dir(b) / f"{song_key(row)}.json" for b in ("claude", "jev")]
        if not all(f.exists() for f in files):
            continue
        claude, jev = (json.loads(f.read_text(encoding="utf-8")) for f in files)
        same = total = sure = sure_same = 0
        for line, jev_labels in jev["labels"].items():
            claude_labels = claude["labels"].get(line, [])
            if len(claude_labels) != len(jev_labels):
                continue
            for c, j, conf in zip(claude_labels, jev_labels, jev["confidence"][line]):
                total += 1
                same += c == j
                if conf >= LOW_CONFIDENCE:
                    sure += 1
                    sure_same += c == j
                if c != j:
                    disagreements[(c, j)] += 1
        pct = lambda n, d: round(100 * n / d, 1) if d else ""
        out.append({"film": row["film"], "title": row["title"], "words": total,
                    "pct_agree": pct(same, total),
                    "pct_agree_when_jev_confident": pct(sure_same, sure),
                    "pct_agree_when_jev_unsure": pct(same - sure_same, total - sure),
                    "jev_unsure_words": total - sure})
    if not out:
        raise SystemExit("no song has been tagged by both backends yet")

    with open(DATA_DIR / "tagger_comparison.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    for r in out:
        print(f"{r['title'][:28]:28} {r['words']:5} words  agree {r['pct_agree']}%  "
              f"(Jev confident: {r['pct_agree_when_jev_confident']}%, unsure: {r['pct_agree_when_jev_unsure']}%)")
    print("most common disagreements (claude → jev):")
    for (c, j), n in disagreements.most_common(8):
        print(f"  {c} → {j}: {n}")
    print("wrote data/tagger_comparison.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_tag = sub.add_parser("tag")
    p_tag.add_argument("titles", nargs="*")
    p_tag.add_argument("--backend", choices=["claude", "jev"], default="claude")
    p_tag.add_argument("--force", action="store_true", help="re-tag songs that already have tags")
    p_tag.add_argument("--workers", type=int, default=4, help="songs tagged in parallel")
    p_sum = sub.add_parser("summarize")
    p_sum.add_argument("--backend", choices=["claude", "jev"], default="claude")
    sub.add_parser("compare")
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("titles", nargs="+")
    args = parser.parse_args()

    if args.command == "tag":
        tag(args.backend, args.titles, args.force, args.workers)
    elif args.command == "summarize":
        summarize(args.backend)
    elif args.command == "compare":
        compare()
    else:
        rows = {r["title"]: r for r in load_songs()}
        for title in args.titles:
            write_input(rows[title])
