# Bollywood lyrics NLP

See README.md for the pipeline and data layout.

The lyrics (`data/lyrics.jsonl`, `data/lyrics/`) are gitignored because they're copyrighted, so a fresh clone
doesn't have them. If a task needs the lyrics and they're missing, rebuild them by following
README.md → "Rebuilding the lyrics" (`pip install -r requirements.txt && python scrape_lyrics.py`, about
15 minutes uncached) before starting. Don't commit lyrics text to this public repo.
