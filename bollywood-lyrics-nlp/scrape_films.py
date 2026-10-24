"""Step 1: scrape the top-N highest-grossing Hindi (Bollywood) films worldwide from Wikipedia.

Source: https://en.wikipedia.org/wiki/List_of_highest-grossing_Hindi_films
(the "Indian films" list mixes in Telugu/Tamil/Kannada films like Baahubali 2 and
Pushpa 2, so the Hindi list is the right definition of "Bollywood" here).

Each film's own Wikipedia page is also fetched to confirm its release year from the
infobox and to record the page URL, which step 2 (soundtracks) will start from.

Usage: python scrape_films.py [--top 10]
Writes data/films.csv and data/films.md.
"""
import argparse
import csv
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://en.wikipedia.org/wiki/List_of_highest-grossing_Hindi_films"
HEADERS = {"User-Agent": "BollywoodLyricsNLP/0.1 (https://github.com/arjungup740/eleventy-base-blog)"}
DATA_DIR = Path(__file__).parent / "data"
CACHE_DIR = Path(__file__).parent / ".cache"


def get_soup(url):
    """Fetch a page (cached on disk so reruns don't re-hit Wikipedia), backing off on 429s."""
    cached = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if cached.exists():
        return BeautifulSoup(cached.read_text(encoding="utf-8"), "lxml")
    for attempt in range(5):
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 429:
            break
        time.sleep(int(resp.headers.get("Retry-After", 0)) or 10 * 2 ** attempt)
    resp.raise_for_status()
    time.sleep(2)  # be polite to Wikipedia
    CACHE_DIR.mkdir(exist_ok=True)
    cached.write_text(resp.text, encoding="utf-8")
    return BeautifulSoup(resp.text, "lxml")


def clean(text):
    text = re.sub(r"\[[^\]]*\]", "", text)  # drop footnote markers like [5] or [b]
    text = " ".join(text.split())
    return re.sub(r"\(\s+", "(", re.sub(r"\s+([,)])", r"\1", text))


def parse_crore(gross):
    """'₹1,148.32 crore' -> 1148.32 (first number if it's a range)."""
    m = re.search(r"[\d,]+(?:\.\d+)?", gross)
    return float(m.group().replace(",", "")) if m else None


def find_worldwide_table(soup):
    # The first section is titled "Highest-grossing Hindi films" (worldwide gross);
    # the next one is the India-only domestic list, so match the heading exactly.
    for table in soup.select("table.wikitable"):
        heading = table.find_previous(["h2", "h3"])
        if heading and clean(heading.get_text()) == "Highest-grossing Hindi films":
            return table
    raise RuntimeError("Worldwide gross table not found; the page layout may have changed")


def infobox_year(film_url):
    soup = get_soup(film_url)
    infobox = soup.select_one("table.infobox")
    if not infobox:
        return None
    for row in infobox.select("tr"):
        label = row.find("th")
        if label and "Release date" in label.get_text():
            years = re.findall(r"\b(?:19|20)\d{2}\b", row.get_text())
            return int(min(years)) if years else None
    return None


def scrape(top):
    soup = get_soup(LIST_URL)
    table = find_worldwide_table(soup)
    header = [clean(th.get_text()) for th in table.find("tr").find_all(["th", "td"])]
    films = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        link = row["Title"].find("a", href=re.compile(r"/wiki/"))
        gross = clean(row["Worldwide gross"].get_text())
        films.append({
            "rank": int(clean(row["Rank"].get_text())),
            "title": clean(row["Title"].get_text()),
            "worldwide_gross": gross,
            "worldwide_gross_crore": parse_crore(gross),
            "list_year": int(clean(row["Year"].get_text())),
            "wiki_url": urljoin(LIST_URL, link["href"]) if link else "",
        })
        if len(films) == top:
            break

    for film in films:
        film["release_year"] = infobox_year(film["wiki_url"]) if film["wiki_url"] else None
        if film["release_year"] and film["release_year"] != film["list_year"]:
            print(f"note: list says {film['title']} is {film['list_year']}, "
                  f"its own page says {film['release_year']}; using the latter")
        film["year"] = film["release_year"] or film["list_year"]
    return films


def write_outputs(films):
    DATA_DIR.mkdir(exist_ok=True)
    fields = ["rank", "title", "year", "worldwide_gross", "worldwide_gross_crore", "wiki_url"]
    with open(DATA_DIR / "films.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(films)

    lines = ["| Rank | Film | Year | Worldwide gross |", "|---:|---|---:|---:|"]
    lines += [f"| {f['rank']} | [{f['title']}]({f['wiki_url']}) | {f['year']} | {f['worldwide_gross']} |"
              for f in films]
    (DATA_DIR / "films.md").write_text(
        f"Source: {LIST_URL} (scraped {time.strftime('%Y-%m-%d')})\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=10)
    write_outputs(scrape(parser.parse_args().top))
