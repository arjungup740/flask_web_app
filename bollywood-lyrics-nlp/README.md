# Bollywood lyrics NLP

Question: how much of the lyrics in top-grossing Bollywood films is in languages other than Hindi,
and is Punjabi overrepresented?

Pipeline:

1. `scrape_films.py`: the top 10 highest-grossing Hindi films worldwide, scraped from Wikipedia → `data/films.csv`, `data/films.md`
2. `scrape_songs.py`: the songs on each film's Wikipedia soundtrack page, with lyricists and singers → `data/songs.csv`, `data/songs.md`.
   Keeps the original Hindi album (and deluxe-edition bonus songs). Dubbed albums, background score, instrumentals,
   reprises, remixes and alternate versions are dropped and listed in `data/songs_skipped.csv` with the reason.
3. `scrape_lyrics.py`: lyrics for each song in original script (from [LRCLIB](https://lrclib.net)) and romanized
   (from [LyricsMint](https://lyricsmint.com), or LRCLIB when it has a romanized copy) → `data/lyrics.jsonl`, `data/lyrics_coverage.csv`.
   73/79 songs have lyrics: 55 in original script (44 Devanagari, 9 Gurmukhi, 2 Arabic/Urdu), 62 romanized, 44 both.
   `lyrics.jsonl` is gitignored because the lyrics are copyrighted; rerun the script to regenerate it
   (`lyrics_coverage.csv` records which source and match each song used, without the text).
4. NLP: language mix (Hindi/Urdu/Punjabi/English), themes, sentiment (to do)

Requires `requests`, `beautifulsoup4`, `lxml`. Fetched pages are cached in `.cache/` (gitignored), so reruns don't re-download.
