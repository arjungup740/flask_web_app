"""Step 3: fetch lyrics for every song in data/songs.csv, in original script and romanized.

Sources:
  - LRCLIB (https://lrclib.net), a free lyrics API. Its Bollywood lyrics are mostly in the
    original script (Devanagari, sometimes Gurmukhi or Urdu), occasionally romanized.
  - LyricsMint (https://lyricsmint.com), which has romanized (Latin-script) lyrics.

A candidate only counts as a match when its title matches the song and either its film/album
or one of its singers matches too, so a same-named song from another film isn't picked up.
Whichever script a source returns is detected from the text itself, so a romanized LRCLIB
hit fills the romanized slot if LyricsMint has nothing.

Usage: python scrape_lyrics.py
Writes (full lyrics are gitignored because they're copyrighted):
  data/lyrics.jsonl: one JSON record per song with both versions, for analysis
  data/lyrics/<NN_film>/<NN_song>.original.txt / .romanized.txt: the same lyrics, for browsing
  data/lyrics_coverage.csv: what was found where and the file paths, no lyrics text (committed)
"""
import csv
import json
import re
import shutil
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urljoin

from scrape_films import DATA_DIR, fetch, get_soup

LRCLIB_SEARCH = "https://lrclib.net/api/search"
MINT_BASE = "https://lyricsmint.com"
SCRIPT_RANGES = {
    "Devanagari": (0x0900, 0x097F),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Arabic/Urdu": (0x0600, 0x06FF),
    "Bengali": (0x0980, 0x09FF),
    "Gujarati": (0x0A80, 0x0AFF),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
}
# Dubbed releases share the film's name ("Chhaava (Telugu)"), so the film check alone isn't enough.
DUBBED = re.compile(r"\b(tamil|telugu|malayalam|kannada)\b", re.I)
DUBBED_SCRIPTS = {"Tamil", "Telugu", "Kannada", "Malayalam"}


def norm(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def title_variants(title):
    """'Destiny – Mann Atkeya' -> also try 'Destiny', 'Mann Atkeya'; drop '(Title Track)' etc."""
    variants = [title, re.sub(r"\s*\(.*?\)", "", title)]
    variants += [part for part in re.split(r"\s+[–-]\s+", title) if part != title]
    return [v.strip() for v in dict.fromkeys(variants) if v.strip()]


def titles_match(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    # Allow "Chaleya (From "Jawan")" style suffixes, but not one-word containment like "Naina".
    return a == b or b.startswith(a + " ") or a.startswith(b + " ") or SequenceMatcher(None, a, b).ratio() >= 0.85


def singer_overlap(song_singers, candidate_artists):
    names = [norm(s) for s in re.split(r",|&| and |\(|\)", song_singers) if len(norm(s)) > 3]
    candidate = norm(candidate_artists)
    return sum(name in candidate for name in names)


def detect_script(text):
    counts = {name: 0 for name in SCRIPT_RANGES}
    latin = 0
    for ch in text:
        cp = ord(ch)
        if ch.isascii() and ch.isalpha():
            latin += 1
        for name, (lo, hi) in SCRIPT_RANGES.items():
            if lo <= cp <= hi:
                counts[name] += 1
    native, n = max(counts.items(), key=lambda kv: kv[1])
    # Original-script lyrics often carry English words in Latin letters, so a modest share of
    # native-script letters is enough; romanized lyrics have essentially none.
    return native if n >= 0.2 * (n + latin) else "Latin"


def lrclib_lookup(song):
    best, best_score = None, 0
    # Exact track-name search first, then a free-text search with the film name for stragglers.
    queries = [({"track_name": v}, v) for v in title_variants(song["title"])]
    queries += [({"q": f"{v} {song['film']}"}, v) for v in title_variants(song["title"])]
    for params, variant in queries:
        try:
            results = json.loads(fetch(LRCLIB_SEARCH, params))
        except Exception as exc:  # LRCLIB still down after retries, or bad JSON: treat as not found
            print(f"  lrclib error for {params}: {exc}")
            continue
        for r in results:
            if r.get("instrumental") or not r.get("plainLyrics"):
                continue
            if not titles_match(variant, r["trackName"]):
                continue
            if DUBBED.search(f"{r.get('albumName') or ''} {r['trackName']}") or \
                    detect_script(r["plainLyrics"]) in DUBBED_SCRIPTS:
                continue
            film_hit = norm(song["film"]) in norm(f"{r.get('albumName') or ''} {r['trackName']}")
            singers = singer_overlap(song["singers"], r.get("artistName") or "")
            if not (film_hit or singers):
                continue
            # Prefer original-script text so the native slot gets filled when possible.
            score = 3 * film_hit + singers + (detect_script(r["plainLyrics"]) != "Latin")
            if score > best_score:
                best, best_score = r, score
        if best:
            break
    if not best:
        return None
    return {
        "lyrics": best["plainLyrics"].strip(),
        "url": f"https://lrclib.net/api/get/{best['id']}",
        "matched": f"{best['trackName']} | {best.get('artistName')} | {best.get('albumName')}",
    }


def mint_lookup(song):
    for variant in title_variants(song["title"]):
        soup = get_soup(f"{MINT_BASE}/search", {"query": variant})
        for a in soup.select("a.song[href]"):
            title = a.find("h3").get_text(strip=True) if a.find("h3") else ""
            film = a.select_one("span.bg-magenta")
            film = film.get_text(strip=True) if film else ""
            meta = a.get_text(" ")
            film_hit = norm(film) == norm(song["film"]) or norm(song["film"]) in norm(film)
            if titles_match(variant, title) and (film_hit or singer_overlap(song["singers"], meta)):
                url = urljoin(MINT_BASE, a["href"])
                lyrics = mint_lyrics(url)
                if lyrics:
                    return {"lyrics": lyrics, "url": url, "matched": f"{title} | {film}"}
    return None


def mint_lyrics(url):
    soup = get_soup(url)
    body = soup.select_one("#lyrics div.text-base")
    if not body:
        return ""
    stanzas = [p.get_text("\n").strip() for p in body.find_all("p")]
    return "\n\n".join(s for s in stanzas if s)


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", norm(text)).strip("_").title() or "Untitled"


def write_lyrics_folders(records):
    """data/lyrics/01_Dangal/03_Gilehriyaan.original.txt, numbered like films.csv and songs.csv."""
    root = DATA_DIR / "lyrics"
    shutil.rmtree(root, ignore_errors=True)  # rebuilt from scratch so renamed songs leave no strays
    track_counts = {}
    for record in records:
        track = track_counts[record["film"]] = track_counts.get(record["film"], 0) + 1
        film_dir = root / f"{int(record['film_rank']):02d}_{slug(record['film'])}"
        stem = f"{track:02d}_{slug(record['title'])}"
        for slot in ("original", "romanized"):
            record[f"{slot}_file"] = ""
            if record[f"{slot}_lyrics"]:
                path = film_dir / f"{stem}.{slot}.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(record[f"{slot}_lyrics"] + "\n", encoding="utf-8")
                record[f"{slot}_file"] = str(path.relative_to(DATA_DIR))


def main():
    with open(DATA_DIR / "songs.csv", encoding="utf-8") as f:
        songs = list(csv.DictReader(f))

    records, coverage = [], []
    for song in songs:
        found = {"original": None, "romanized": None}
        for source, hit in (("lrclib", lrclib_lookup(song)), ("lyricsmint", mint_lookup(song))):
            if not hit:
                continue
            script = detect_script(hit["lyrics"])
            slot = "romanized" if script == "Latin" else "original"
            if not found[slot]:
                found[slot] = {**hit, "source": source, "script": script}

        record = {"film_rank": song["film_rank"], "film": song["film"], "title": song["title"],
                  "singers": song["singers"]}
        row = dict(record)
        for slot in ("original", "romanized"):
            hit = found[slot] or {}
            record[f"{slot}_lyrics"] = hit.get("lyrics", "")
            for key in ("script", "source", "url", "matched"):
                record[f"{slot}_{key}"] = row[f"{slot}_{key}"] = hit.get(key, "")
            row[f"{slot}_lines"] = len([l for l in hit.get("lyrics", "").splitlines() if l.strip()])
        records.append(record)
        coverage.append(row)
        print(f"{song['film']} / {song['title']}: "
              f"original={found['original']['script'] if found['original'] else '-'}, "
              f"romanized={'yes' if found['romanized'] else '-'}")

    write_lyrics_folders(records)
    for record, row in zip(records, coverage):
        row["original_file"], row["romanized_file"] = record["original_file"], record["romanized_file"]

    with open(DATA_DIR / "lyrics.jsonl", "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    with open(DATA_DIR / "lyrics_coverage.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)

    either = sum(bool(r["original_lyrics"] or r["romanized_lyrics"]) for r in records)
    both = sum(bool(r["original_lyrics"] and r["romanized_lyrics"]) for r in records)
    print(f"\n{either}/{len(records)} songs have lyrics; {both} have both scripts; "
          f"{sum(bool(r['original_lyrics']) for r in records)} original, "
          f"{sum(bool(r['romanized_lyrics']) for r in records)} romanized")


if __name__ == "__main__":
    main()
