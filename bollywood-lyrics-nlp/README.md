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
4. `tag_languages.py`: Claude tags the language of every word of every song (Hindi/Urdu, Punjabi, English,
   other named languages, plus vocables and names, which are left out of the shares), following
   `language_tagging_guidelines.md` → `data/song_languages.csv`, one row per song: % of words in each language,
   counted as sung (repeated choruses included). For songs in original script it also gives the % of lines and
   words written in Gurmukhi, a tagger-free cross-check. See [Running the language tagging](#running-the-language-tagging).
5. Themes, sentiment (to do)

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

## Running the language tagging

Needs the lyrics (above) and an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=...        # from https://platform.claude.com
python tag_languages.py tag         # tags every song with lyrics that isn't tagged yet
python tag_languages.py summarize   # → data/song_languages.csv
```

- Tagging all 73 songs takes roughly 20–30 minutes (4 songs in parallel) and costs roughly $5–15 with
  Claude Opus 5.5. Reruns skip songs that are already tagged, so an interrupted run picks up where it stopped.
- `tag "Chaleya" "Faraatta"` tags just those songs; `--force` re-tags (e.g. after changing the guidelines);
  `prepare "Chaleya"` writes the numbered lines that would be sent, without calling the API.
- The tagger has to return exactly one label per word. If it miscounts a line it's retried twice with the exact
  mismatches; if a line is still off, that line is left out of the song's shares and `lines_left_out` says how many.
- Per-word tags go to `data/language_tags/` (gitignored, since they contain the lyrics). `song_languages.csv`
  holds only percentages, so it's committed.
- The tagging rules live in `language_tagging_guidelines.md`; edit that file to change them, then rerun with `--force`.

### Rebuilding everything from scratch

To redo the film and song lists too (e.g. after the box-office rankings change), run all three steps in order.
Steps 1 and 2 also need network access to `en.wikipedia.org`:

```bash
python scrape_films.py      # --top N for a different number of films
python scrape_songs.py
python scrape_lyrics.py
```

Wikipedia gets edited, so this can change the film list, the songs, or both; `git diff data/` shows what moved.
