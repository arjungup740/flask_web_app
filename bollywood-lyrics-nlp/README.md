# Bollywood lyrics NLP

Question: how much of the lyrics in top-grossing Bollywood films is in languages other than Hindi,
and is Punjabi overrepresented?

Pipeline:

1. `scrape_films.py`: the top 10 highest-grossing Hindi films worldwide, scraped from Wikipedia → `data/films.csv`, `data/films.md`
2. `scrape_songs.py`: the songs on each film's Wikipedia soundtrack page, with lyricists and singers → `data/songs.csv`, `data/songs.md`.
   Keeps the original Hindi album (and deluxe-edition bonus songs). Dubbed albums, background score, instrumentals,
   reprises, remixes and alternate versions are dropped and listed in `data/songs_skipped.csv` with the reason.
3. Lyrics for each song (to do)
4. NLP: language mix (Hindi/Urdu/Punjabi/English), themes, sentiment (to do)

Requires `requests`, `beautifulsoup4`, `lxml`. Fetched pages are cached in `.cache/` (gitignored), so reruns don't re-download.
