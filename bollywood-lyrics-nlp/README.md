# Bollywood lyrics NLP

Question: how much of the lyrics in top-grossing Bollywood films is in languages other than Hindi,
and is Punjabi overrepresented?

Pipeline:

1. `scrape_films.py`: the top 10 highest-grossing Hindi films worldwide, scraped from Wikipedia → `data/films.csv`, `data/films.md`
2. Songs from each film's soundtrack (to do)
3. Lyrics for each song (to do)
4. NLP: language mix (Hindi/Urdu/Punjabi/English), themes, sentiment (to do)

Requires `requests`, `beautifulsoup4`, `lxml`.
