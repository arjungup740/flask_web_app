# Bollywood lyrics NLP

Question: how much of the lyrics in top-grossing Bollywood films is in languages other than Hindi,
and is Punjabi overrepresented?

Pipeline:

1. `scrape_films.py`: the top 10 highest-grossing Hindi films worldwide, scraped from Wikipedia → `data/films.csv`, `data/films.md`
2. `scrape_songs.py`: the songs on each film's Wikipedia soundtrack page, with lyricists and singers → `data/songs.csv`, `data/songs.md`.
   Keeps the original Hindi album (and deluxe-edition bonus songs). Dubbed albums, background score, instrumentals,
   reprises, remixes and alternate versions are dropped and listed in `data/songs_skipped.csv` with the reason.
3. `scrape_lyrics.py`: lyrics for each song in original script (from [LRCLIB](https://lrclib.net)) and romanized
   (from [LyricsMint](https://lyricsmint.com), or LRCLIB when it has a romanized copy) → `data/lyrics.jsonl` (one record per song, for analysis),
   `data/lyrics/<NN_film>/<NN_song>.original.txt` / `.romanized.txt` (for browsing; numbered as in `films.csv` and `songs.md`),
   and `data/lyrics_coverage.csv`.
   73/79 songs have lyrics: 55 in original script (44 Devanagari, 9 Gurmukhi, 2 Arabic/Urdu), 62 romanized, 44 both.
   `lyrics.jsonl` and `lyrics/` are gitignored because the lyrics are copyrighted; see [Rebuilding the lyrics](#rebuilding-the-lyrics)
   (`lyrics_coverage.csv` records which source and match each song used, without the text).
4. NLP: language mix (Hindi/Urdu/Punjabi/English), themes, sentiment (to do)

## Rebuilding the lyrics

The lyrics (`data/lyrics.jsonl` and `data/lyrics/`) aren't committed, so a fresh clone has to regenerate them.
The song list they're built from (`data/songs.csv`) is committed, so this only needs step 3:

```bash
cd bollywood-lyrics-nlp
pip install -r requirements.txt
python scrape_lyrics.py
```

- Takes about 15 minutes on a fresh clone: it pauses 2 seconds between requests to be polite to the sites.
  Every fetched page is cached in `.cache/` (gitignored), so later reruns finish in seconds.
- Needs network access to `lrclib.net` and `lyricsmint.com`.
- It ends by printing a summary line; the last run gave
  `73/79 songs have lyrics; 44 have both scripts; 55 original, 62 romanized`.
  Run `git diff data/lyrics_coverage.csv` afterwards: no diff means you got the same matches as the committed run.
  A diff means a lyrics site changed (a song added, removed or re-matched), which is worth a look before analysing.
- Rate limiting (HTTP 429) and server errors (5xx) are retried automatically with backoff. If a source stays down,
  those songs are logged as `lrclib error ...` and come out without lyrics. Rerun later; cached pages aren't re-fetched,
  but failed ones are.
- To force fresh downloads (e.g. to pick up newly published lyrics), delete `.cache/` first.

### Rebuilding everything from scratch

To redo the film and song lists too (e.g. after the box-office rankings change), run all three steps in order.
Steps 1 and 2 also need network access to `en.wikipedia.org`:

```bash
python scrape_films.py      # --top N for a different number of films
python scrape_songs.py
python scrape_lyrics.py
```

Wikipedia gets edited, so this can change the film list, the songs, or both; `git diff data/` shows what moved.
