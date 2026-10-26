# Selecting an OCR Model for a Legal Corpus

Routing decides *whether* to OCR (`extraction-source-routing.md`). This decides
*which* model. Same corpus, different backends can differ by more than the
text-layer-vs-OCR choice does.

## The decisive metric is invented citations

Recall (character error rate) is nearly useless for a citation index: a model
that gets 95% of characters right still produces a corpus full of wrong decree
numbers, and nothing downstream flags a plausible-but-wrong reference.

Rank candidate models on, in order:

1. **Invented references** — dotted legal refs (`1.00.71`, `13.99`) the model
   emits that do not appear in ground truth. Worst failure; points at an
   instrument that may not exist. Weight this above everything else.
2. **Recovered article numbers** vs ground truth — recall.
3. **Hallucinated bare article numbers** — must be zero for both.
4. **Line structure** — newlines returned per page; decides whether any
   line-anchored parser can work at all.

A model can win on recall and still lose the corpus.

## You need ground truth

An A/B without ground truth is opinion. Get one of:

- a reference OCR of the same PDF by a different tool (`.txt` beside the
  `.pdf`) — best, cheap, and already the truth if it came from a human
- the user's read of the rendered pages
- vision over rendered pages (rate-limited; batch the renders)

Never score an OCR model against the native text layer. On a CMap-corrupted
corpus the layer is under suspicion for exactly the defect in dispute, so it
inverts the result — the model that is actually correct looks like the failure.

## Once you have real ground truth, similarity metrics invert the ranking

Bag-of-characters recall is not merely uninformative here — it is actively
misleading, because digit transposition *preserves the character multiset*.
A measurement against a reference `.txt`:

| candidate | recall | precision | numeric fidelity |
|---|---|---|---|
| native (CMap-transposed) | 0.870 | **0.990** | **every reference wrong** |
| OCR route | 0.607 | 0.871 | read the digits correctly |

The transposed layer wins both similarity metrics while `1.02.202` reads as
`22.121.1`, `1423` as `2211`, the issue number `5029` as `8365`, and the
lam-alef ligatures collapse (`لله`→`هلل`, `الأول`→`االول`). A transposition
defect is invisible to a character histogram by construction.

So: **never let recall or precision stand as the quality verdict.** Pair every
similarity number with an explicit numeric-fidelity check, and report the two
side by side even when they disagree — the disagreement is the finding.

```python
# ground-truth tokens must appear verbatim in the candidate
for tok in ("1.02.202", "1423", "2002", "5029", "2282"):
    assert tok in candidate, tok
# and the corrupted variants must NOT appear
for bad in ("22.121.1", "2211"):
    assert bad not in candidate, bad
```

## Check for a diacritics ratio before reading the output

Printed Arabic legal text carries no harakat. A generative model completing the
page emits fully vowelled text — measured 0.1342 harakat-per-letter against a
ground truth of 0.0000. That single ratio distinguishes transcription from
composition, and composition means fabrication: the same run invented a library
stamp and a Moroccan supplement that appear nowhere in the source, and rendered a
plausible-but-wrong ministry name (`وزارة العدل والحريات` →
`وزارة العدل والشؤون المدنية`).

Any non-trivial harakat ratio disqualifies the output as synthetic. Score it on
invention, not fidelity — and do not spend the read on its prose, which will
look better than the ground truth's.

## Check published Arabic-OCR benchmarks before running a local model A/B

A local A/B on this corpus costs minutes per page on a CPU host, so check what
is already published before spending it. Vendor aggregate scores (OCRBench,
DocVQA) do not discriminate for this work — they are dominated by English and by
document *understanding* rather than character-exact transcription. Two
findings change the decision directly:

**A traditional recogniser can beat every VLM on Arabic.** Measured on 140
Arabic pages / 3,197 lines (CER, lower is better):

| system | CER | WER |
|---|---|---|
| Kraken-OpenITI (CNN-LSTM, in-domain) | **3.1** | **18.2** |
| olmOCR-2-7B (VLM) | 10.5 | 43.8 |
| Qwen3-VL-8B (VLM) | 11.3 | 44.4 |
| Qwen3-VL-2B (VLM) | 17.6 | 60.0 |
| DeepSeek-OCR (VLM) | 20.8 | 66.7 |
| Tesseract-ara (traditional, out-of-domain) | 24.6 | 77.8 |

The spread across all five VLMs (10.5–20.8) sits inside the spread between the
two traditional engines (3.1–24.6). **If your reference OCR is a traditional
engine rather than a VLM, you have already chosen the better-performing class**,
and moving the corpus to the cloud scanner beats scaling a VLM.

**Failure modes appear only in VLM output.** Repetition collapse, markup
emission, and off-script generation (Latin characters inside Arabic lines) were
absent from both traditional systems across every page tested. So the presence of
these in any output is itself a positive signal that a VLM produced it —
useful as a cheap classifier, not just a quality complaint.

**Model size helps but does not close the gap.** Qwen3-VL 4B→8B moved Arabic
CER 17.6→11.3 (36% relative). That is real, and it is still 3.6x worse than the
traditional recogniser. Read a size upgrade as a partial improvement to an
approach with a ceiling, not as a fix — and expect the same memorisation
signature (see the resolution A/B above) to persist at 8B, since recall is a
capacity-independent property.

**Arabic is the weak language, and interventions do not transfer across
scripts.** Vendor comparison tables list Arabic as the model family's weakest
supported script. In the same study, inference-time interventions *reversed
direction* between Greek and Arabic: script masking was highly damaging in Greek
and nearly inert in Arabic; M3ID helped Greek Qwen models and harmed Arabic ones;
VCD did the reverse. **Text-only post-OCR correction improved several Greek
systems and degraded nearly all Arabic systems** — so never port a
post-correction step validated on another script.

The robust cross-script finding is the perturbation test: under controlled
character perturbation, *every* VLM moved further from the displayed text than
either traditional system, with no overlap between the families. That is
language-prior repair, and it is what the diacritics ratio detects in your own
output (see above).

## A resolution A/B is a diagnostic, not a fix — and flat scores are a memorisation signature

Raising the pixel budget on a suspected-under-reading model is the obvious first
move and it works, partway. Measured on one page against a reference OCR,
body text going 15.4px → 22.9px took harakat-per-letter from **0.4687 to
0.2068**, and prose accuracy visibly improved. It did not make the output
citable. Run the A/B, report both columns, and say plainly that it did not close
the gap — "resolution was a cause" is not "resolution was the fix".

The decisive column is digit recovery, and it must *move*:

| | 15.4px body | 22.9px body |
|---|---|---|
| harakat/letter | 0.4687 | 0.2068 |
| reference digit tokens recovered | **40/70** | **40/70** |
| law number correct | yes | yes |

Recovery identical to the token across a 1.5x change in legibility means the
model is not reading the digits — it is reproducing references it recognises
from training and dropping the rest. **A metric that does not respond to a
change you made deliberately is measuring something other than the thing you
fixed**, and for legal references that something is memorised prior. A model
that were reading would improve; one that is recalling cannot, because recall
has no resolution dependence.

Corollary on levers: temperature `0`, an explicit "do not add text that is not
visible" instruction, and higher resolution together still produced invented
letterhead and a plausible-but-wrong ministry name. When the model is weak at
character-exact transcription — an instruct/reasoning VLM asked to transcribe —
none of those are the lever. An OCR-trained model is the different lever; test
that before tuning anything on the prompt side.

## A hallucination-rejection gate can select the artifact it was protecting against

The gate was right and the outcome was still wrong. A vision route emitted zero
recognised article markers, so the gate rejected it on coverage (`article
coverage 0 < 70% of native layer's 7`) and fell back to the native text layer —
the corrupt artifact under investigation. The document indexed from the worse
source, with a log line explaining why.

This is not a tuning bug. A gate that rejects the better option *without an
alternative* leaves the defect as the default, so its rejection arm must name a
destination that is also known-good. When the only fallback is the suspect
artifact the branch has no correct outcome, and the honest report is "no citable
source available for this document" — not a document indexed from the layer
already proven wrong. **Read the fallback arm of any quality gate, not just its
accept arm**: the rejection path is the one that runs silently.

## Do not assume one permutation explains digit damage

Measured on a single document, the corruption mixed forms: `1423`→`2211` is a
consistent transposition, while `2002`→`0260` and `5029`→`8365` are half-shifts.
A single swap table recovers the first and not the others, so a partial recovery
reads as a failed repair when it is really an unmodelled second fault. Report
per-token outcomes rather than a single "recovered/not recovered" verdict.

## Prefer the test that needs no alignment, and distrust any verdict that rests on few samples

Two alignment-based approaches were tried on this corpus and **both produced a
confident wrong verdict**, which is the whole reason to prefer the
inventory-based test:

- matching digit tokens by length paired unrelated numbers — four-digit
  tokens match four-digit tokens, so `2211` came out as `-> 1423 / 2002 / 1414
  / 1993` all at the same count, a table that means nothing;
- `difflib` alignment on native-vs-reference text yielded 17 digit pairs at
  character level and 4 at word level, then printed a confident "NOT LEARNABLE"
  with `2 -> {6: 1, 0: 1, 9: 3, 4: 2}` — that was an artefact of the sample
  size, not a finding, and the second (cleaner) run reduced the evidence further.

**Per-digit character inventory is the test to reach for first.** A permutation
preserves the multiset of digit characters, so comparing counts against a
trusted reference decides the question with no alignment and no threshold to
argue about:

| digit | reference | native | status |
|---|---|---|---|
| 1 | 132 | 30 | LOST 102 |
| 4 | 47 | 5 | LOST 42 |
| 9 | 51 | 4 | LOST 47 |
| 6 | 3 | 15 | EXTRA +12 |

Digits are being destroyed and replaced, not relabelled — so no substitution
table exists and no digit repair is available. **Plan for a re-OCR or a trusted
reference from the start rather than designing the repair.**

Two rules make this stick. First, **assert a minimum sample before any
alignment-based verdict and return INCONCLUSIVE below it** (~30 aligned pairs
here): printing a confident table off four pairs is worse than printing
nothing, because the reader cannot tell which they are looking at. Second, **an
inconclusive method is not a finding** — when an approach under-performs, say so
and change method rather than reporting its output with a caveat, and keep the
discarded attempts so the negative result is auditable.

## A quality gate can be green on a document with no valid citations

The same document reported `errors=0 warnings=0`. Structure checks, article-marker
counts and masthead patterns all passed — none of them read the digits. Treat a
green gate as a statement about structure only, and add a numeric-fidelity stage
before it can gate a corpus.

## Worked result

Same 9-page document, both models on one host, scored against a reference OCR:

| | model A (OCR-tuned) | model B (base VLM) |
|---|---|---|
| dotted refs correct | 8/9 | **9/9** |
| **invented refs** | **3** | **0** |
| article numbers | 19/22 | **20/22** |
| newlines per page | 8 | **179** |

The general-purpose model beat the Arabic-specialised one. Non-obvious enough
that it justifies insisting on ground truth rather than impressions — a single
clean-looking parse is a structural gate result, not evidence of text fidelity.

Structure gap (8 vs 179 newlines) also showed the earlier "document structure
is a model capability ceiling" reading was wrong: it was one model's ceiling.

## Prompt variants will not fix structure

If a model returns a page as one line, changing the prompt does not change it.
Measured on identical pages: production prompt, an Arabic line-ordering
prompt, and a merged prompt with an explicit "emit one output line per printed
line" — all returned zero newlines, output similarity 0.93–0.99.

When testing prompt variants, **test the combination as well as the
alternatives** if the working hypothesis is that the instructions compose.
Testing them only as rivals tests a weaker claim than you believe.

If prompts do not work, split run-on text parser-side (see SKILL.md Pitfalls).

## Transient backend crashes are retryable, not fatal

`{"error":"model runner has unexpectedly stopped"}` is a runner crash, not a
rejection: the same pages succeeded on the next attempt. Retry 5xx and
transport errors with bounded backoff; do **not** retry 4xx, which is
deterministic. Record failed page numbers and surface them — a parse that
silently emits 14/16 pages indexes as if complete.

Always re-sweep with retry enabled before concluding a model cannot read a
page; a sweep without retry understates the backend.

## Switching models

Keep the endpoint and the API style as one unit — base URL (`ollama` →
`/api/generate`, `openai` → `/v1/chat/completions`) is a single setting pair.
Mismatching them 404s every call while looking configured.

After any switch, assert three things: the effective model string parses
through settings, the model is present on the host's model list, and the
endpoint answers. A one-character typo in a model name (`GGUF`→`GUFF`) fails
every call with no useful error — diff the configured name against what the
host actually serves.

## GGUF cannot be loaded by transformers

A repo shipping only `*.gguf` plus an `mmproj-*.gguf` projector has no
safetensors and no HF `config.json`; `from_pretrained` cannot read it, even
when the HF metadata says `library: transformers` (inherited from the base
model). Use `llama-cpp-python`, passing the projector as the chat handler's
`clip_model_path`.

The projector must match the model's quantisation family — an F16 projector
with a Q4 model is the usual cause of blank output. Tie both to one quant
variable. Prefer serving the GGUF through Ollama when a host already has it:
no notebook, no session limit, reproducible.

## When the switch is justified

State the evidence and its limits together: which document, which metric, and
that a single document is one data point. Name the hard document that has not
been re-measured after the switch.