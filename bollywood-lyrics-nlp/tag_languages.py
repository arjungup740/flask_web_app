"""Step 4: word-level language shares per song, tagged by Claude.

  python tag_languages.py tag [--force] ["Song title" ...]
      Tags every song that has lyrics (or just the titles given) and isn't tagged yet; --force
      re-tags. Needs the `anthropic` package and an API key (ANTHROPIC_API_KEY).
      Writes data/language_tags/input/<NN_film>__<NN_song>.txt (the numbered lines sent)
      and data/language_tags/output/<same name>.json (one label per word).
  python tag_languages.py summarize
      Writes data/song_languages.csv from the tag files.
  python tag_languages.py prepare "Song title" ...
      Only writes the input files, e.g. to inspect what would be sent.

Each song is sent with language_tagging_guidelines.md as the system prompt. The lyrics used
are the original script when available, else romanized. Percentages count every word as sung
(choruses included); vocables and names are left out of the denominator. For original-script
songs it also reports the share of lines (and words) written in Gurmukhi vs Devanagari,
which doesn't depend on the tagger.
"""
import argparse
import csv
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scrape_films import DATA_DIR
from scrape_lyrics import SCRIPT_RANGES

TAG_DIR = DATA_DIR / "language_tags"
GUIDELINES = Path(__file__).parent / "language_tagging_guidelines.md"
MODEL = "claude-opus-5-5"
TOKEN = re.compile(r"[\wऀ-෿؀-ۿ'’]+(?:-[\wऀ-෿؀-ۿ'’]+)*")
OTHER_LANGUAGES = ["Haryanvi", "Bhojpuri", "Rajasthani", "Marathi", "Sanskrit", "Persian", "Arabic", "Spanish", "Other"]
LABELS = ["hindi_urdu", "punjabi", "english", "vocable", "name"] + [f"other:{l}" for l in OTHER_LANGUAGES]
EXCLUDED = {"vocable", "name"}
MAX_ATTEMPTS = 3

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


def tag_song(client, row):
    import anthropic

    text, lines = write_input(row)
    prompt = "Tag every token of this song.\n\n" + text
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with client.beta.messages.stream(
                model=MODEL,
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

    (TAG_DIR / "output").mkdir(parents=True, exist_ok=True)
    (TAG_DIR / "output" / f"{song_key(row)}.json").write_text(
        json.dumps({"labels": labels, "notes": result["notes"], "model": MODEL}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    warning = f" (still {len(mismatches)} mismatched lines, left out of the shares)" if mismatches else ""
    return f"{row['title']}: tagged{warning}"


def tag(titles, force, workers):
    import anthropic

    songs = load_songs()
    if titles:
        songs = [r for r in songs if r["title"] in titles]
        missing = set(titles) - {r["title"] for r in songs}
        if missing:
            raise SystemExit(f"no lyrics for: {', '.join(sorted(missing))}")
    if not force:
        songs = [r for r in songs if not (TAG_DIR / "output" / f"{song_key(r)}.json").exists()]
    print(f"tagging {len(songs)} songs with {MODEL}")

    client = anthropic.Anthropic(max_retries=5)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for message in pool.map(lambda r: tag_song(client, r), songs):
            print(message)


def summarize():
    out = []
    for row in load_songs():
        tag_file = TAG_DIR / "output" / f"{song_key(row)}.json"
        if not tag_file.exists():
            continue
        text_used, lines = tokenized_lines(row)
        tags = json.loads(tag_file.read_text(encoding="utf-8"))["labels"]

        labels, other_langs = Counter(), Counter()
        mismatched = [f"L{i}" for i, t in enumerate(lines, 1) if len(tags.get(f"L{i}", [])) != len(t)]
        for i, tokens in enumerate(lines, 1):
            if f"L{i}" in mismatched:
                continue
            for label in tags[f"L{i}"]:
                if label.startswith("other:"):
                    other_langs[label.split(":", 1)[1]] += 1
                    label = "other"
                labels[label] += 1
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
        if text_used == "original":
            # Script share, independent of the tagger: lines (and words) written in Gurmukhi vs Devanagari.
            line_scripts = Counter(token_script(" ".join(t)) for t in lines)
            tok_scripts = Counter(token_script(t) for tokens in lines for t in tokens)
            result["pct_lines_gurmukhi"] = pct(line_scripts["Gurmukhi"], line_scripts["Gurmukhi"] + line_scripts["Devanagari"])
            result["pct_words_gurmukhi"] = pct(tok_scripts["Gurmukhi"], tok_scripts["Gurmukhi"] + tok_scripts["Devanagari"])
        out.append(result)

    fields = list(dict.fromkeys(k for r in out for k in r))
    with open(DATA_DIR / "song_languages.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote data/song_languages.csv ({len(out)} songs)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_tag = sub.add_parser("tag")
    p_tag.add_argument("titles", nargs="*")
    p_tag.add_argument("--force", action="store_true", help="re-tag songs that already have tags")
    p_tag.add_argument("--workers", type=int, default=4, help="songs tagged in parallel")
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("titles", nargs="+")
    sub.add_parser("summarize")
    args = parser.parse_args()

    if args.command == "tag":
        tag(args.titles, args.force, args.workers)
    elif args.command == "prepare":
        rows = {r["title"]: r for r in load_songs()}
        for title in args.titles:
            write_input(rows[title])
    else:
        summarize()
