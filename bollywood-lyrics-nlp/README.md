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
4. `tag_languages.py`: tags the language of every word of every song (Hindi/Urdu, Punjabi, English,
   other named languages, plus vocables and names, which are left out of the shares), following
   `language_tagging_guidelines.md`, with either of two taggers: Claude, or TypeSafe's Jev (one multiple-choice
   question per word, with probabilities and a confidence). → `data/song_languages.csv` (Claude) /
   `data/song_languages_jev.csv` (Jev), one row per song: % of words in each language, counted as sung
   (repeated choruses included). For songs in original script it also gives the % of lines and words written
   in Gurmukhi, a tagger-free cross-check. See [Running the language tagging](#running-the-language-tagging).
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

Needs the lyrics (above) and an API key for the tagger you use. There are two:

| | Claude (default) | Jev (`--backend jev`) |
|---|---|---|
| Key | `ANTHROPIC_API_KEY` ([platform.claude.com](https://platform.claude.com)) | `TYPESAFE_API_KEY` ([console.typesafe.ai](https://console.typesafe.ai)) |
| How | Reads the whole song, returns one label per word | One multiple-choice question per word, with the whole song as context; returns a probability for every language and a confidence |
| Cost, all 73 songs | roughly $5–15 | well under $1 |
| Output | `data/song_languages.csv` | `data/song_languages_jev.csv`, which adds probability-weighted shares (`soft_pct_*`: a word that's 90% Punjabi counts as 0.9) and `low_confidence_words` |

```bash
export ANTHROPIC_API_KEY=...                  # and/or TYPESAFE_API_KEY=...
python tag_languages.py tag                   # Claude: tags every song with lyrics that isn't tagged yet
python tag_languages.py summarize             # → data/song_languages.csv
python tag_languages.py tag --backend jev     # Jev
python tag_languages.py summarize --backend jev
python tag_languages.py compare               # word-by-word agreement on songs both have tagged
```

- Reruns skip songs that backend has already tagged, so an interrupted run picks up where it stopped.
  `tag "Chaleya" "Faraatta"` tags just those songs; `--force` re-tags (e.g. after changing the guidelines);
  `prepare "Chaleya"` writes the numbered lines that would be sent, without calling an API.
- Claude has to return exactly one label per word. If it miscounts a line it's retried twice with the exact
  mismatches; if a line is still off, that line is left out of the song's shares and `lines_left_out` says how many.
  Jev can't miscount: each word is its own question.
- Jev's docs say English is its strongest language, so check it before trusting it here: tag a few songs with
  both backends and run `compare`. It writes `data/tagger_comparison.csv` with each song's agreement, split by
  whether Jev was confident (≥ 0.5), and prints the most common disagreements.
- Jev requests carry the whole song plus a batch of word questions (80 by default); a batch over Jev's context
  limit is split in half automatically. The answer options are shuffled per word, since Jev leans toward the first
  option listed. The model is pinned to `jev-1.14.0` so confidences stay comparable between runs.
- Per-word tags go to `data/language_tags/output_claude/` and `output_jev/` (gitignored, since they contain the
  lyrics). The CSVs hold only numbers, so they're committed.
- The tagging rules live in `language_tagging_guidelines.md`. Claude gets that file whole; Jev gets a condensed
  version in `JEV_CRITERIA` in `tag_languages.py`, so change both. Then rerun with `--force`.

### Rebuilding everything from scratch

To redo the film and song lists too (e.g. after the box-office rankings change), run all three steps in order.
Steps 1 and 2 also need network access to `en.wikipedia.org`:

```bash
python scrape_films.py      # --top N for a different number of films
python scrape_songs.py
python scrape_lyrics.py
```

Wikipedia gets edited, so this can change the film list, the songs, or both; `git diff data/` shows what moved.
