# pdfdiff — semantic PDF comparison

Measures **how much two PDFs differ by meaning** — not by exact wording — and
prints a single similarity %% plus a detailed change list.

A faithful reword ("payment due in 30 days" → "must be paid within thirty days")
should count as *unchanged*. A one-word negation ("must pay" → "must **not**
pay") should count as a *material change*. Plain text diffs get both backwards;
pdfdiff is built to get both right.

> **No external PDF library.** Text extraction is written from scratch on the
> Python standard library (`zlib` only) — no PyMuPDF, no pdfminer, no OCR
> binaries. The parser reconstructs reading-order paragraphs and headings itself,
> and produces byte-identical word output to PyMuPDF on the sample documents. See
> [PDF extraction from scratch](#pdf-extraction-from-scratch).

## How it works

```
PDF A ─┐
       ├─▶ extract ─▶ chunk ─▶ embed ─▶ match ─▶ judge ─▶ score ─▶ report
PDF B ─┘ (structure) (3 levels)        (greedy)  (meaning)
```

1. **extract** — a from-scratch, dependency-free PDF parser (stdlib `zlib` only)
   that reconstructs reading-order blocks, paragraphs and headings. No PyMuPDF,
   no OCR — see [PDF extraction](#pdf-extraction-from-scratch).
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
pip install -e .            # core: PDF parsing + matching, zero ML deps, any Python
pip install -e ".[local]"   # + local embeddings & cross-encoder judge (torch)
pip install -e ".[all]"     # everything
```

The core install has **no third-party PDF dependency** — text extraction is
implemented from scratch on the standard library.

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

### Example 3 — telling *different documents* apart

Comparing two **unrelated** documents (a 30-page "System Design Review" vs a
50-page "Enterprise Architecture Review") that happen to share generic
infra/security boilerplate:

```
| Granularity | Similarity | Difference |
| ---         | ---        | ---        |
| section     | 51.7%      | 48.3%      |
| paragraph ★ | 17.3%      | 82.7%      |
| sentence    | 39.3%      | 60.7%      |

paragraph changes: 80 changed · 190 deleted · 74 added
```

Two revisions of one document score ~99% at **every** granularity (Examples 1–2).
These don't — and the *shape* of the scores is the tell:

- **Low paragraph similarity (17%)** with **190 deleted + 74 added** blocks =
  the actual content doesn't line up. Different documents.
- **Higher section similarity (52%)** = at the whole-page level they're about the
  same *topic* (deployment/security/monitoring), so coarse pairs look related.

So a **coarse score much higher than the fine score** means *"same subject area,
different content"* — not *"same document, lightly edited."* That spread is the
signal the three granularities exist to surface.

📄 Full generated output: [`samples/largepdfs3_report.md`](samples/largepdfs3_report.md)
— ~1,800 lines, because unrelated documents produce hundreds of added/deleted
blocks (exactly the point).

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
Check `--granularity sentence` first (most robust to layout). If section/paragraph
look off, inspect what the extractor produced:
```bash
python -c "from pdfdiff.pdfparse.extract import extract_blocks; \
[print(b.is_heading, repr(b.text[:80])) for b in extract_blocks('a.pdf')[:20]]"
```

**A PDF produces no text / no blocks.**
The extractor handles digital PDFs (FlateDecode streams, simple/Type0 fonts). It
does **not** do OCR, so scanned/image-only PDFs yield nothing — there's no text
layer to read. Encrypted PDFs and fonts without a ToUnicode map or standard
encoding may also extract poorly; those are outside this tool's scope.

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

## PDF extraction from scratch

Text extraction is implemented in `pdfdiff/pdfparse/` with **no third-party PDF
library** — only Python's standard library (`zlib` for stream decompression).
The stages:

| Module | Responsibility |
| --- | --- |
| `lexer.py` | Tokenise PDF syntax into the object model (dicts, arrays, strings, names, refs, streams) |
| `objects.py` | The eight PDF object types as Python values |
| `filters.py` | Stream decoding: FlateDecode (+ PNG/TIFF predictors), ASCII85, ASCIIHex |
| `document.py` | Object scan, trailer/`/Root`, indirect-ref resolution, page tree with attribute inheritance |
| `fonts.py` + `encodings.py` | Byte-code → Unicode via `/ToUnicode`, or `/Encoding` + `/Differences` (WinAnsi base) |
| `content.py` | Content-stream interpreter — tracks the CTM × text matrix to place every run with x/y + font size |
| `layout.py` | Reconstruct reading-order lines → paragraphs; flag headings by font size; **rebuild tables** by clustering cells into rows/columns |
| `markdown.py` | Render blocks (headings, paragraphs, tables) as Markdown |

This gives the chunker real structure (paragraphs, headings, tables) instead of
guessing from blank lines, and verified **byte-identical word output** to PyMuPDF
on the sample documents.

## PDF → Markdown (`pdf2md`)

The same extractor powers a standalone converter that dumps a PDF's text as
structured Markdown — headings as `#`, paragraphs as paragraphs, and **tables
reconstructed into real `| col | col |` grids** (cells grouped into rows by
y-position and columns by x-position).

```bash
pdf2md input.pdf                 # print Markdown to stdout
pdf2md input.pdf -o out.md       # write to a file
pdf2md input.pdf --no-pages      # omit <!-- page N --> markers
```

A table in the source PDF comes out as:

```markdown
| Service | SLA | Owner |
| --- | --- | --- |
| API | 99.5% | Platform |
| DB | 99.9% | Infra |
```

Sample outputs: [`samples/large_test_document_v1.md`](samples/large_test_document_v1.md)
and [`samples/hard_pdf_v1.md`](samples/hard_pdf_v1.md) (see its page 28 for the table).

**Scope:** digital PDFs with FlateDecode streams and simple/Type0 fonts. Out of
scope: scanned/image PDFs (no OCR), encryption, and CID fonts lacking a ToUnicode
map. Contributions to widen coverage (LZW, xref-stream edge cases) are welcome.

## Development

```bash
python -m pytest tests/ -q
```

`tests/test_score.py` validates the matcher and the scoring formula (including
the reword and negation cases) using a fake judge — no models or network needed.

After cloning, enable the shared git hooks (auto-appends co-author trailers):

```bash
git config core.hooksPath .githooks
```
