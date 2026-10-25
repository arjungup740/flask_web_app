# Word-level language tagging guidelines

You are tagging the language of every word in a Bollywood song's lyrics. The input is the
song as numbered lines of tokens, every line as sung (repeated choruses included):

```
L1: इश्क़ में दिल बना है
L2: ...
```

Return JSON with one label per token, in order, for every line:

```json
{"labels": {"L1": ["hindi_urdu", "hindi_urdu", "shared", "hindi_urdu", "hindi_urdu"], "L2": [...]},
 "notes": "one or two sentences on anything unusual in this song"}
```

The number of labels for a line must equal the number of tokens on it.

## Labels

| Label | Use for |
|---|---|
| `hindi_urdu` | Hindi or Urdu (one bucket: they're one spoken language with different literary registers). Includes Urdu/Persian-origin words that are standard in Hindi film lyrics (*ishq, junoon, khwaab, mohabbat*) when they appear in a Hindi line. |
| `punjabi` | Punjabi. Markers: *ni, ve, tenu/tainu, menu/mainu, sanu, tusi, assi, vich, naal, da/di/de* (as possessives), *kudi, munda, hoya, gaya ae, kardi, laggdi, chaleya, sohneya*, the *-eya/-iya* vocative endings, *ae* for *hai*. |
| `english` | English words, including ones written in Devanagari or Gurmukhi (e.g. *t-shirt*, *party*, *selfie*). |
| `other:<Language>` | Any other language, named: `other:Haryanvi`, `other:Bhojpuri`, `other:Marathi`, `other:Spanish`, `other:Arabic`, `other:Persian`, etc. |
| `shared` | A word that is genuinely the same in Hindi and Punjabi **and** whose line gives no clue which language is being sung. Use sparingly (see the context rule). |
| `vocable` | Non-lexical sounds and fillers: *oh, ho, aa, hey, yeah, la la, na na, oye* used as a shout, humming. |
| `name` | Proper nouns: people, places, deities, the film's title (*Pathaan, Bajrangbali, Jawan*). |

## The context rule (most important)

Many everyday words exist in both Hindi and Punjabi (*dil, yaar, ishq, main, tu, mera, pyaar,
rang*). Label each word by the language of the **phrase it's in**, not the word on its own:

- In "तेरा हुआ मैं सब को छोड़ के" every word is `hindi_urdu`: the line is Hindi.
- In "ਤੇਰਾ ਹੋਇਆ ਮੈਂ ਯਾਰ ਵੇ" / "tera hoya main yaar ve" every word is `punjabi`: *hoya* and *ve* make the line Punjabi.
- Only when a phrase has no marker of either language (e.g. a line that is just "dil dil dil")
  use `shared`, unless the surrounding lines are clearly in one language, in which case use that.

Lines can switch language mid-line; label each part separately.

## Script is evidence, not the answer

Text in Gurmukhi script is very likely Punjabi and text in Devanagari is very likely Hindi, but
publishers sometimes write Punjabi in Devanagari and the other way round. Judge the words.

## Other rules

- Words in Devanagari/Gurmukhi/Urdu script or in romanization are tagged the same way.
- A token that is a mis-split fragment or junk (credits, timestamps) gets `vocable`.
- Don't skip lines or tokens, and don't merge them.
