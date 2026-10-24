"""Step 2: scrape the song list for each film in data/films.csv from its Wikipedia soundtrack page.

For each film we find its "<Film> (soundtrack)" article and read the track-listing tables.
Kept: songs from the original Hindi album (including deluxe-edition bonus songs).
Skipped (written to data/songs_skipped.csv with a reason so the choices can be audited):
  - dubbed albums (Tamil, Telugu, Malayalam, Kannada)
  - background score sections and instrumental tracks
  - reprises, remixes and other alternate versions of a song already in the album

When a table has no Lyrics column, the lyricist comes from the album's
"All lyrics are written by ..." note, or failing that from the article text.

Usage: python scrape_songs.py
Writes data/songs.csv and data/songs_skipped.csv.
"""
import csv
import re

from scrape_films import DATA_DIR, clean, get_soup

DUBBED_LANGUAGES = ("tamil", "telugu", "malayalam", "kannada")
VERSION_WORDS = re.compile(
    r"\b(reprise|remix|version|stripped|unplugged|lo-?fi|mashup|extended|acoustic|"
    r"arabic|female|male|sad|slowed|reverb)\b", re.I)
NAME = r"[A-Z][\w.'–-]*(?: [A-Z][\w.'–-]*)*"


def find_soundtrack_url(film_url):
    soup = get_soup(film_url)
    # The film page's Music section opens with a "Main article: X (soundtrack)" hatnote.
    for hatnote in soup.select("div.hatnote"):
        link = hatnote.find("a", href=re.compile(r"_\(soundtrack\)"))
        if link:
            return link["href"]
    return film_url.split("#")[0] + "_(soundtrack)"


def section_headings(table):
    h2 = table.find_previous("h2")
    h3 = table.find_previous("h3")
    # Only count the h3 if it sits under the same h2.
    if h3 and h2 and h3.find_previous("h2") is not h2:
        h3 = None
    return (clean(h2.get_text()) if h2 else "", clean(h3.get_text()) if h3 else "")


def page_lyricist(soup):
    text = clean(soup.get_text(" "))
    m = re.search(rf"lyrics (?:are |were )?(?:written|penned) by ({NAME}(?: and {NAME})?)", text)
    return m.group(1) if m else ""


def album_lyricist_note(table):
    """'All lyrics are written by X.' sits just above the table (or in its caption)."""
    node = table.find("caption")
    texts = [node.get_text(" ")] if node else []
    prev = table.find_previous(string=re.compile(r"All lyrics"))
    if prev and prev.find_parent(["h2", "h3"]) is None and prev.find_next("table") is table:
        texts.append(prev.parent.get_text(" "))
    for text in texts:
        m = re.search(rf"All lyrics (?:are |were )?(?:written|penned) by ({NAME}(?: and {NAME})?)", clean(text))
        if m:
            return m.group(1)
    return ""


def split_title(raw):
    """'"Marham" (Pehle Bhi Main)' -> ('Marham', 'Pehle Bhi Main')."""
    m = re.match(r'^"(.+?)"\s*(.*)$', raw)
    title, rest = (m.group(1), m.group(2)) if m else (raw, "")
    rest = re.sub(r"\((?:Co-)?composed by [^)]*\)", "", rest, flags=re.I)
    qualifier = " ".join(re.findall(r"\(([^)]*)\)", rest))
    return title.strip(), qualifier.strip()


def base_name(title):
    return re.sub(r"\s*\(.*?\)\s*", " ", title).strip().lower()


def parse_tracklist(table):
    rows = table.find_all("tr")
    header = None
    for tr in rows:
        cells = [clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        if header is None:
            if "Title" in cells:
                header = cells
            continue
        if len(cells) != len(header) or cells[0].startswith("Total length"):
            continue
        yield dict(zip(header, cells))


def scrape_film(film):
    st_url = find_soundtrack_url(film["wiki_url"])
    soup = get_soup(st_url)
    fallback_lyricist = page_lyricist(soup)
    kept, skipped, seen = [], [], set()

    for table in soup.select("table.tracklist"):
        h2, h3 = section_headings(table)
        caption = clean(table.find("caption").get_text(" ")) if table.find("caption") else ""
        album = " / ".join(x for x in (h3, caption) if x) or h2
        note_lyricist = album_lyricist_note(table)

        for row in parse_tracklist(table):
            title, qualifier = split_title(row["Title"])
            lyrics = row.get("Lyrics", "")
            singers = row.get("Singer(s)", row.get("Artist(s)", ""))
            song = {
                "film_rank": film["rank"],
                "film": film["title"],
                "album": album,
                "track_no": row.get("No.", "").rstrip("."),
                "title": title,
                "qualifier": qualifier,
                "lyricists": lyrics or note_lyricist or fallback_lyricist,
                "lyricist_source": "track listing" if lyrics else
                                   "album note" if note_lyricist else
                                   "article text" if fallback_lyricist else "",
                "singers": singers,
                "composers": row.get("Music", ""),
                "length": row.get("Length", ""),
                "soundtrack_url": st_url,
            }

            reason = ""
            if "score" in h2.lower():
                reason = "background score"
            elif any(lang in f"{h3} {caption}".lower() for lang in DUBBED_LANGUAGES):
                reason = "dubbed album"
            elif "instrumental" in f"{lyrics} {singers}".lower():
                reason = "instrumental"
            elif VERSION_WORDS.search(f"{title} {qualifier}"):
                reason = "alternate version"
            elif base_name(title) in seen or (qualifier and qualifier.lower() in seen):
                # e.g. "Marham" (Pehle Bhi Main) or "Tu Jo Mila (Dekhna Na Mudke)"
                reason = "alternate version"

            if reason:
                skipped.append({**song, "skip_reason": reason})
            else:
                seen.add(base_name(title))
                kept.append(song)
    return kept, skipped


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path, songs):
    lines = []
    for film in dict.fromkeys(s["film"] for s in songs):
        lines += [f"## {film}", "", "| # | Song | Lyricist(s) | Singer(s) |", "|---:|---|---|---|"]
        rows = [s for s in songs if s["film"] == film]
        lines += [f"| {i} | {s['title']} | {s['lyricists']} | {s['singers']} |" for i, s in enumerate(rows, 1)]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    with open(DATA_DIR / "films.csv", encoding="utf-8") as f:
        films = list(csv.DictReader(f))
    songs, skipped = [], []
    for film in films:
        kept, dropped = scrape_film(film)
        print(f"{film['title']}: {len(kept)} songs ({len(dropped)} skipped)")
        songs += kept
        skipped += dropped
    write_csv(DATA_DIR / "songs.csv", songs)
    write_csv(DATA_DIR / "songs_skipped.csv", skipped)
    write_markdown(DATA_DIR / "songs.md", songs)
    print(f"total: {len(songs)} songs, {len(skipped)} skipped")
