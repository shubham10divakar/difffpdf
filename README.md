# pdfdiff — semantic PDF comparison

Measures **how much two PDFs differ by meaning** — not by exact wording — and
prints a single similarity %% plus a detailed change list.

A faithful reword ("payment due in 30 days" → "must be paid within thirty days")
should count as *unchanged*. A one-word negation ("must pay" → "must **not**
pay") should count as a *material change*. Plain text diffs get both backwards;
pdfdiff is built to get both right.

## How it works

```
PDF A ─┐
       ├─▶ extract ─▶ chunk ─▶ embed ─▶ match ─▶ judge ─▶ score ─▶ report
PDF B ─┘  (+OCR auto) (3 levels)        (greedy)  (meaning)
```

1. **extract** — pull the text layer (PyMuPDF); OCR scanned pages as a fallback.
2. **chunk** — split into *section / paragraph / sentence* units (all three are
   computed so you get a coarse-to-fine picture).
3. **embed** — vectorise chunks so we can cheaply align A with B.
4. **match** — greedily pair the most-similar chunks; leftovers are added/deleted.
   Order-independent, so reflowed/reordered content still matches.
5. **judge** — re-score the *ambiguous* matched pairs by meaning. This is the
   step that fixes the negation and reword cases above.
6. **score** — length-weighted formula → similarity %% + change list.

### The metric

With `w` = chunk word count and `w̄` = the mean weight of a matched pair:

```
              Σ_pairs (1-s)·w̄  +  Σ_deleted w_A  +  Σ_added w_B
difference =  ─────────────────────────────────────────────────
              Σ_pairs w̄        +  Σ_deleted w_A  +  Σ_added w_B

similarity% = 100 · (1 - difference)
```

`s` is the meaning-similarity of a matched pair (1.0 = same meaning). A reworded
pair gets `s≈1` and contributes ~nothing; a negation flip on a big clause gets
low `s` and high `w̄`, so it moves the number a lot. The denominator is the total
content mass of both documents, so the result is always 0–100.

## Install

```bash
pip install -e .            # core: works on any Python, zero ML deps
pip install -e ".[local]"   # + local embeddings & cross-encoder judge (torch)
pip install -e ".[ocr]"     # + OCR for scanned pages (needs the Tesseract binary)
pip install -e ".[all]"     # everything
```

> **Python 3.14 note:** `torch` (pulled by `[local]`) may not have wheels yet.
> Either use a Python 3.12 venv for the local backends, or use the install-free
> `--embed-backend hash` for matching plus a cloud/Ollama judge.

## Usage

```bash
pdfdiff A.pdf B.pdf                              # all defaults (local backends)
pdfdiff A.pdf B.pdf --judge anthropic            # best meaning judge (needs key)
pdfdiff A.pdf B.pdf --embed-backend hash --judge none   # zero-dependency, lexical
pdfdiff A.pdf B.pdf --granularity sentence --output json
```

### Flags

| Flag | Choices (default) | Meaning |
| --- | --- | --- |
| `--granularity` | section, paragraph, sentence, **all** | unit to feature; `all` computes every level |
| `--embed-backend` | hash, **local**, openai, voyage | vectors used for matching |
| `--judge` | **local**, ollama, anthropic, openai, none | meaning judge for ambiguous pairs |
| `--ocr` | **auto**, never, always | OCR scanned pages |
| `--sim-threshold` | float (**0.95**) | pairs at/above this meaning-sim count as unchanged |
| `--judge-band LO HI` | floats (**0.5 0.99**) | only judge pairs whose embedding sim is in range |
| `--match-floor` | float (**0.45**) | min embedding sim to call two chunks a match |
| `--max-chunks` | int (none) | cap chunks/doc/granularity (cost guard) |
| `--output` | **text**, json, md | report format |

### Backends at a glance

| `--judge` | Engine | Score | Explanation | Needs |
| --- | --- | --- | --- | --- |
| `local` | cross-encoder | ✅ strong | ✗ | `[local]` extra |
| `ollama` | local LLM | ✅ | ✅ | Ollama running |
| `anthropic` | Claude | ✅ best | ✅ | `ANTHROPIC_API_KEY` |
| `openai` | GPT | ✅ | ✅ | `OPENAI_API_KEY` |
| `none` | embeddings only | lexical/semantic per embed backend | ✗ | — |

API keys are read from the **environment**, never flags, so they don't leak into
shell history.

## Example

### Example 1 — edits buried in boilerplate

Comparing two 30-page revisions of a design document (~6,400 words each) with the
**free, offline** local backends — no API key required:

```bash
pdfdiff v1.pdf v2.pdf \
  --embed-backend local \
  --judge local --judge-model cross-encoder/stsb-distilroberta-base \
  --granularity all --output md
```

The two files are mostly identical boilerplate with a handful of edits buried in
them. pdfdiff reports ~99% similar and pinpoints every change:

```
| Granularity | Similarity | Difference |
| ---         | ---        | ---        |
| section     | 99.1%      | 0.9%       |
| paragraph ★ | 99.1%      | 0.9%       |
| sentence    | 99.2%      | 0.8%       |

## Changes — section
- CHANGED · sim 0.87 · Section 7.5    "monitoring" → "AI-assisted monitoring"
- CHANGED · sim 0.73 · Section 27.3   + quarterly security audit requirement
- CHANGED · sim 0.72 · Section 25.8   + disaster-recovery appendix
- CHANGED · sim 0.70 · Section 12.1   + MFA mandatory for admins
- CHANGED · sim 0.68 · Section 16.4   backup frequency weekly → daily
- CHANGED · sim 0.65 · Section 3.2    retention 30 → 90 days
- CHANGED · sim 0.65 · Section 21.7   SLA target 99.5% → 99.9%
```

A plain text diff would drown these seven edits in thousands of identical lines;
pdfdiff surfaces just the seven and scores how much each one's *meaning* shifted.

> The local cross-encoder gives a similarity **score** but no written
> explanation. For a one-line "what changed" on each entry, use a generative
> judge: `--judge ollama` (free, local) or `--judge anthropic` (needs a key).

### Example 2 — the hard cases (reorder, table digits, subtle inserts)

Two 50-page revisions with deliberately tricky changes, same local/free command:

```bash
pdfdiff hard_v1.pdf hard_v2.pdf \
  --embed-backend local --judge local \
  --judge-model cross-encoder/stsb-distilroberta-base \
  --granularity all --output md
```

```
| Granularity | Similarity | Difference |
| ---         | ---        | ---        |
| section     | 99.3%      | 0.7%       |
| paragraph ★ | 99.3%      | 0.7%       |
| sentence    | 99.5%      | 0.5%       |

CHANGED · sim 0.60 · p8         "API 99.5%"  →  "API 99.95%"   (single digit in a table)
CHANGED · sim 0.81 · §22.1      "monitoring" → "AI-assisted monitoring"
ADDED   · §12.2                 "New MFA enforcement policy added."
ADDED   · §35.4                 "Disaster recovery drill findings appended."
CHANGED · sim 0.58 · §40.0      section reordered (40.0 ↔ 40.4 swapped on page 40)
```

What this demonstrates:

- **Order-independent matching.** Sections 40.0–40.4 were shuffled. A line diff
  would report *everything after page 40* as changed; pdfdiff matches by content,
  so only the two moved sections light up.
- **Fine-grained chunking.** It pulled `99.5% → 99.95%` out of a table — a
  one-digit change — and flagged it.
- **Materiality, by design.** A running-header bump (`Review 2026 → 2027`) was
  scored as *equivalent* by the judge and not flagged. If you need every literal
  token change, raise `--sim-threshold 0.995` or add a lexical pass
  (`--embed-backend hash --judge none`).

## Recipes

Common commands by scenario. (`difffpdf` and `pdfdiff` are interchangeable.)

### Fastest, zero install
No ML stack, no keys — pure lexical matching. Good for a quick first look.
```bash
pdfdiff a.pdf b.pdf --embed-backend hash --judge none
```

### Best accuracy, fully free & offline (recommended default)
Local embeddings + local cross-encoder judge. Catches rewording and negation.
```bash
pdfdiff a.pdf b.pdf                       # all defaults already do this
pdfdiff a.pdf b.pdf --embed-backend local --judge local
```

### With written "what changed" explanations
Use a generative judge — free via Ollama, or highest quality via Claude.
```bash
# Free, local — needs Ollama running (https://ollama.com)
ollama pull llama3.1
pdfdiff a.pdf b.pdf --judge ollama --judge-model llama3.1

# Highest quality — needs a key in the environment
export ANTHROPIC_API_KEY=sk-ant-...       # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
pdfdiff a.pdf b.pdf --judge anthropic

export OPENAI_API_KEY=sk-...
pdfdiff a.pdf b.pdf --judge openai
```

### Cloud embeddings (better matching on huge/varied docs)
```bash
export OPENAI_API_KEY=sk-...
pdfdiff a.pdf b.pdf --embed-backend openai

export VOYAGE_API_KEY=...                  # Anthropic's recommended embeddings
pdfdiff a.pdf b.pdf --embed-backend voyage --judge anthropic
```

### Scanned / image-only PDFs (OCR)
Needs the `[ocr]` extra and the Tesseract binary installed.
```bash
pdfdiff scan1.pdf scan2.pdf --ocr always   # OCR every page
pdfdiff a.pdf b.pdf --ocr auto             # default: OCR only text-less pages
pdfdiff a.pdf b.pdf --ocr never            # text layer only, fastest
```

### Pick the comparison granularity
```bash
pdfdiff a.pdf b.pdf --granularity sentence    # finest — small edits
pdfdiff a.pdf b.pdf --granularity paragraph   # balanced
pdfdiff a.pdf b.pdf --granularity section     # coarse — which areas changed
pdfdiff a.pdf b.pdf --granularity all         # all three (default)
```

### Large documents — control cost & runtime
```bash
# Only judge the genuinely ambiguous pairs, and cap chunk count.
pdfdiff big1.pdf big2.pdf --judge anthropic --judge-band 0.6 0.95 --max-chunks 800
```

### Tune sensitivity
```bash
pdfdiff a.pdf b.pdf --sim-threshold 0.99    # strict: even tiny rewords count as changes
pdfdiff a.pdf b.pdf --sim-threshold 0.85    # lenient: only flag bigger shifts
pdfdiff a.pdf b.pdf --match-floor 0.6       # require stronger matches (more add/del)
```

### Output formats
```bash
pdfdiff a.pdf b.pdf --output text                 # human-readable (default)
pdfdiff a.pdf b.pdf --output md   > report.md     # Markdown report file
pdfdiff a.pdf b.pdf --output json > report.json   # machine-readable
```

### Use the JSON in automation
```bash
# Print just the paragraph-level similarity %.
pdfdiff a.pdf b.pdf --output json | python -c "import sys,json; print(json.load(sys.stdin)['granularities']['paragraph']['similarity_pct'])"
```

> **Windows PowerShell:** use a backtick `` ` `` for line continuation instead of
> `\`, and set keys with `$env:NAME="..."` instead of `export`.

## Cost control

Only matched pairs whose embedding similarity falls inside `--judge-band` reach
the judge — near-identical and clearly-unrelated pairs skip it. Tighten the band
or set `--max-chunks` for large documents.

## Troubleshooting

**`torch` / `sentence-transformers` won't install (often on brand-new Python).**
The `[local]` backends need `torch`, which can lag the newest Python releases.
Options, in order of least effort:
```bash
# 1. Run with no ML stack at all — lexical matching, works on any Python:
pdfdiff a.pdf b.pdf --embed-backend hash --judge none
# 2. Use a generative judge (only needs httpx, no torch):
pdfdiff a.pdf b.pdf --embed-backend hash --judge ollama      # or --judge anthropic
# 3. Get real local models by using a Python version torch ships wheels for:
py -3.12 -m venv .venv    # then: pip install -e ".[local]"
```

**The headline similarity looks absurd (e.g. 30% for near-identical PDFs).**
The document probably has no blank lines / unusual layout, so section/paragraph
chunking merged it into one block. Check `--granularity sentence` (most robust to
layout); if section/paragraph still look off, the text extraction is the issue —
inspect it with `--ocr never` vs `--ocr always`.

**`OCR requested but dependencies are missing` / `tesseract is not installed`.**
Install the extra *and* the Tesseract binary (the pip package is only a wrapper):
```bash
pip install "difffpdf[ocr]"
# Windows: install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki
# macOS:   brew install tesseract     Linux: apt-get install tesseract-ocr
```

**`--judge ollama` errors / connection refused.**
Ollama isn't running or the model isn't pulled:
```bash
ollama serve                 # start the server (or launch the Ollama app)
ollama pull llama3.1         # pull the model you pass to --judge-model
# Non-default host? export OLLAMA_HOST=http://host:11434
```

**`--judge anthropic` / `openai` / `voyage` says the key is missing.**
Keys come from the environment, never flags:
```bash
export ANTHROPIC_API_KEY=sk-ant-...    # PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

**`UnicodeEncodeError` when printing on Windows.**
The CLI forces UTF-8 output, but if you embed it elsewhere, set
`PYTHONUTF8=1` or pipe to a file with `--output md > report.md`.

**Comparison is slow on large PDFs.**
Matching is `O(chunks_a × chunks_b)`. Cap it with `--max-chunks`, use a coarser
`--granularity`, and narrow `--judge-band` so fewer pairs reach the judge.

## Development

```bash
python -m pytest tests/ -q
```

`tests/test_score.py` validates the matcher and the scoring formula (including
the reword and negation cases) using a fake judge — no models or network needed.
