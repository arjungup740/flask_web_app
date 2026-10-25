"""Step 4 (pilot): word-level language shares per song.

  python tag_languages.py prepare "Chaleya" "Faraatta" ...
      Tokenizes each song's lyrics (original script when available, else romanized) into
      numbered lines: data/language_tags/input/<NN_film>__<NN_song>.txt
  (a tagger then writes data/language_tags/output/<same name>.json, following
   language_tagging_guidelines.md)
  python tag_languages.py summarize
      Checks every tagged line has one label per token and writes data/song_languages.csv.

Percentages count every word as sung (choruses included). Vocables and names are left out of
the denominator. For original-script songs it also reports the share of lines (and tokens)
written in Gurmukhi vs Devanagari, which is independent of the tagger.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from scrape_films import DATA_DIR
from scrape_lyrics import SCRIPT_RANGES

TAG_DIR = DATA_DIR / "language_tags"
TOKEN = re.compile(r"[\wऀ-෿؀-ۿ'’]+(?:-[\wऀ-෿؀-ۿ'’]+)*")
EXCLUDED = {"vocable", "name"}


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
        return list(csv.DictReader(f))


def song_key(row):
    path = row["original_file"] or row["romanized_file"]
    film_dir, stem = Path(path).parent.name, Path(path).name.split(".")[0]
    return f"{film_dir}__{stem}"


def tokenized_lines(row):
    text_used = "original" if row["original_file"] else "romanized"
    text = (DATA_DIR / row[f"{text_used}_file"]).read_text(encoding="utf-8")
    lines = [TOKEN.findall(line) for line in text.splitlines()]
    return text_used, [tokens for tokens in lines if tokens]


def prepare(titles):
    (TAG_DIR / "input").mkdir(parents=True, exist_ok=True)
    (TAG_DIR / "output").mkdir(parents=True, exist_ok=True)
    rows = {r["title"]: r for r in load_songs()}
    for title in titles:
        row = rows[title]
        text_used, lines = tokenized_lines(row)
        body = "\n".join(f"L{i}: {' '.join(tokens)}" for i, tokens in enumerate(lines, 1))
        header = f"# {row['film']} / {row['title']} ({text_used} text, {len(lines)} lines)\n"
        path = TAG_DIR / "input" / f"{song_key(row)}.txt"
        path.write_text(header + body + "\n", encoding="utf-8")
        print(path.relative_to(DATA_DIR.parent))


def summarize():
    out = []
    for row in load_songs():
        key = song_key(row) if (row["original_file"] or row["romanized_file"]) else None
        tag_file = TAG_DIR / "output" / f"{key}.json"
        if not key or not tag_file.exists():
            continue
        text_used, lines = tokenized_lines(row)
        tags = json.loads(tag_file.read_text(encoding="utf-8"))["labels"]

        labels, mismatched = Counter(), []
        for i, tokens in enumerate(lines, 1):
            line_labels = tags.get(f"L{i}", [])
            if len(line_labels) != len(tokens):
                mismatched.append(f"L{i}")
                continue
            labels.update("other" if l.startswith("other:") else l for l in line_labels)
        if mismatched:
            print(f"warning: {row['title']}: label count != token count on {', '.join(mismatched)}; "
                  "those lines are left out")

        other_langs = Counter(l.split(":", 1)[1] for line in tags.values() for l in line if l.startswith("other:"))
        words = sum(n for label, n in labels.items() if label not in EXCLUDED)
        identified = words - labels["shared"]
        pct = lambda n, d: round(100 * n / d, 1) if d else ""
        result = {
            "film": row["film"], "title": row["title"], "text_used": text_used,
            "words": words,
            "pct_hindi_urdu": pct(labels["hindi_urdu"], words),
            "pct_punjabi": pct(labels["punjabi"], words),
            "pct_english": pct(labels["english"], words),
            "pct_other": pct(labels["other"], words),
            "other_languages": "; ".join(f"{k} {v}" for k, v in other_langs.most_common()),
            "pct_shared": pct(labels["shared"], words),
            "pct_punjabi_of_identified": pct(labels["punjabi"], identified),
            "vocables_and_names": labels["vocable"] + labels["name"],
        }
        if text_used == "original":
            # Script share, independent of the tagger: lines (and tokens) written in Gurmukhi vs Devanagari.
            line_scripts = Counter(token_script(" ".join(t)) for t in lines)
            tok_scripts = Counter(token_script(t) for tokens in lines for t in tokens)
            indic_lines = line_scripts["Gurmukhi"] + line_scripts["Devanagari"]
            indic_toks = tok_scripts["Gurmukhi"] + tok_scripts["Devanagari"]
            result["pct_lines_gurmukhi"] = pct(line_scripts["Gurmukhi"], indic_lines)
            result["pct_tokens_gurmukhi"] = pct(tok_scripts["Gurmukhi"], indic_toks)
        out.append(result)

    fields = list(dict.fromkeys(k for r in out for k in r))
    with open(DATA_DIR / "song_languages.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    for r in out:
        print(r)


if __name__ == "__main__":
    if sys.argv[1:2] == ["prepare"]:
        prepare(sys.argv[2:])
    elif sys.argv[1:2] == ["summarize"]:
        summarize()
    else:
        sys.exit(__doc__)
