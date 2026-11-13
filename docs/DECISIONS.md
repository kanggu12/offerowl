# Decision steps and small decision models

Many of Offerowl's steps decide rather than write: what kind of line a posting line is, how strongly the evidence
covers it, whether a sentence claims more than its evidence, whether two statements contradict each other. This page
asks whether a small decision model can take such steps, in Korean as well as English, and answers with a measurement:
the decision layer that makes the question testable, the numbers, and the verdict per step. In short, none has passed.

Writing never goes through this layer. The one AI backend a person chose still writes everything a person reads.

## The decision layer

`src/decide/` answers the four decision questions through one call:

```python
import decide
decide.decide("claim", [{"claim": "Built the CI pipeline.", "evidence": "I helped build the CI pipeline."}])
# [{"label": "overclaim", "confidence": None, "scores": {}, "backend": "rules", "ms": 0.1}]
```

| Task | Labels | Fields of an item | Where Offerowl decides it today |
|---|---|---|---|
| `line_kind` | duty, requirement, preferred | `text` | the posting parser, by section heading (`src/cover.py`) |
| `coverage` | strong, weak, none | `line`, `evidence` (a list of texts) | the cover planner's word matching or agent call, the interview audit's term rule and judge |
| `claim` | overclaim, supported | `claim`, `evidence` | `factcheck.claim_issues` |
| `contradiction` | contradiction, consistent | `a`, `b` | the interview audit's consistency pass (agent) |

Every backend answers the same question with the same labels (`decide.TASKS`), and every result has the same shape:
the label, a confidence (the label's probability, none for the rules, and a stated one for the agent and Jev), the
scores per label, the backend, and the milliseconds the decision took.

| Backend | What answers | Where the inputs go | Needs |
|---|---|---|---|
| `rules` (default) | the rule checks Offerowl already has | nowhere | nothing |
| `agent` | the AI backend of `src/llm.py`, asked for typed JSON under a schema, many items per call | where that backend is (a signed-in CLI sends them to its provider; a local server keeps them) | the backend |
| `laya` | Laya, a decision model run on this PC's CPU | nowhere | the model files (below), numpy and tokenizers, and onnxruntime or torch |
| `vega` | Vega, the engine Laya's maker published next, run on this PC through the maker's own package | nowhere | the package (`pip install "laya>=0.4.23"`) and the reader's files (below) |
| `jev` | Jev, a hosted decision model, through a gateway | off this PC, to the gateway and the model's maker | a key and an explicit consent setting |

The backend comes from the call, else `OFFEROWL_DECIDE`, else `rules`. Nothing changes for a person who does not set
it. `python3 src/decide/cli.py list` shows each backend, whether it can answer now, and where its inputs go;
`python3 src/decide/cli.py run <task> <items.json> --backend <name>` decides a file of items.

The rules backend, for a single item:
- `line_kind` reads the line's own words, since a line on its own has no heading: a "nice to have" or 우대 cue makes
  it preferred, a qualification cue ("experience", "years", 경험, 이상) a requirement, anything else a duty. With its
  heading, the posting parser decides the kind exactly, and this step does not arise.
- `coverage` applies the interview audit's term rule to the given texts: strong at 60 percent of the line's content
  words, weak at 30 percent, else none.
- `claim` is `factcheck.claim_issues`.
- `contradiction` combines the audit's and the practice feedback's signals: the same unit with another number, the
  same year with another month, or a first-person claim on one side against a scope limit on the other.

## Laya on this PC

Laya (Apache 2.0) reads a state and a typed question and scores each option at its own marker in one forward pass of a
bidirectional encoder. It writes no text. Three checkpoints and one third-party ONNX export were measured:

| Variant | Encoder | Parameters | Tokens | Files | Runtime here | Reads Korean |
|---|---|---|---|---|---|---|
| `english` | ModernBERT-large | 421M | 512 | 0.84 GB | torch | no |
| `multilingual` | mmBERT-base | 322M | 1024 | 0.68 GB | torch | yes |
| `typed-decisions` | ModernBERT-large, tuned on its maker's own benchmark | 421M | 1024 | 0.84 GB | torch | no |
| `english-onnx` | the English checkpoint, exported to ONNX by a third party | 421M | 512 | 1.69 GB | onnxruntime | no |
| `english-onnx-int8` | the same export, quantized to INT8 | 421M | 512 | 0.42 GB | onnxruntime | no |

How it runs:
- `src/decide/laya.py` reads the published files itself. The input layout and the decision head follow the
  published model code, and the weights load strictly into that architecture, so no downloaded code runs. On the
  model card's own example and the evaluation below, the torch path and the ONNX export give the same logits to four
  decimals.
- The ONNX export traced its head's attention at 512 tokens, so its graph runs only at that length. Every row is
  padded to 512 tokens, which makes the export slower than the torch path for short inputs.
- The INT8 export moves the logits enough to flip answers (on the card's example, one of four), and it scores lower
  below.
- Text with Hangul goes to `multilingual`; other text to the English variant named by `OFFEROWL_LAYA_EN` (default:
  the first of `english-onnx-int8`, `english-onnx`, `english`, `typed-decisions` on this PC). `OFFEROWL_LAYA_MODEL`
  fixes one variant for everything.
- Files live in `OFFEROWL_LAYA_DIR` (default `~/.cache/offerowl/laya`). Nothing downloads unless a person runs
  `python3 src/decide/cli.py fetch <variant>` or sets `OFFEROWL_LAYA_DOWNLOAD=1`. Downloads come from pinned
  revisions and are checked against pinned sha256 hashes.
- The fitted temperatures of each checkpoint are applied, clamped to 0.5 to 5 as the maker's runtime does. The
  confidence is the top probability after that; the maker says the shipped checkpoints are over-confident until they
  are refitted on one's own data, and nothing here refits them.
- `OFFEROWL_LAYA_THREADS` sets the CPU threads (default 4).

Each `coverage` item gives Laya one state per evidence text (a state holds about 320 tokens on the English
checkpoint), and the text with the highest expected strength decides, so one text that shows the line is enough, as
for the other backends.

## Vega on this PC

Vega (Apache 2.0) came from Laya's maker on 2026-11-05, with laya 0.4.23. It reads the state with a frozen language
model, the reader, and answers each typed question with a small engine on top of the reader's features, so it reads
Korean as well as its reader does. Every answer also says whether to trust it: a conformal prediction set, an abstain
flag, and a route, `auto` or `review`. Two readers of the maker's repository were measured: the default
Qwen3.5-0.8B (1.7 GB) and Qwen3.5-4B.

How it runs:
- `src/decide/vega.py` calls the maker's own package (vegaml, which comes with laya 0.4.23 or newer), so unlike the
  Laya backend, code from the download runs. A person installs it: `pip install "laya>=0.4.23"`.
- The engine's repository is pinned to the revision measured (`4d20502`). The reader comes from its own repository as
  the package resolves it; the 0.8B was measured at `2fc0636`.
- Nothing downloads unless a person runs `python3 src/decide/cli.py fetch vega` (or `vega:4b`) or sets
  `OFFEROWL_VEGA_DOWNLOAD=1`. Otherwise the loader is told to stay offline, so not even an update check leaves the PC;
  the measurement below ran in a container with no network at all.
- Each item is one state, a coverage item with all its evidence texts, since the reader takes long states.
- The confidence is the chosen option's probability, as for Laya. The route, the abstain flag and the set come with
  each result.
- `OFFEROWL_VEGA_READER` picks the reader (empty for the 0.8B, `4b`, or a repository or folder the package takes),
  `OFFEROWL_VEGA_DEVICE` the device (`cpu`, the default, or `cuda`) and `OFFEROWL_VEGA_THREADS` the CPU threads
  (default 4). The package advises one thread for these readers; here one thread took three times as long as eight
  for the same 161 decisions (376 seconds against 123), with the same answers.

## Jev

Jev is a closed, hosted decision model. `src/decide/jev.py` sends one System One request per decision
(`POST <url>/v1/systemone` with the model name, the item as one state, a posting line as plain text and the others as
an object of readable fields, and the same typed question Laya gets). It reads the choice, the confidence Jev states,
and the probability of each option when the gateway gives them; a question Jev declines is reported as declined, and a
busy gateway (429, 502, 503, 529) is asked again after the wait it names, three times in all. It is off unless both
settings are given:

| Setting | Meaning |
|---|---|
| `OFFEROWL_JEV_KEY` | the gateway key |
| `OFFEROWL_JEV_SEND=1` | consent that decision inputs (posting lines, evidence, sentences) leave this PC |
| `OFFEROWL_JEV_URL` | the gateway (default `https://openrouter.ai/api`; the maker's own endpoint is `https://api.typesafe.ai`) |
| `OFFEROWL_JEV_MODEL` | the model name (default `typesafe/jev-1.14`) |

Only the task's fields leave the PC, never an item's id or other keys. The list command and `decide.backend_info()`
always show where the inputs would go. The client follows the gateway's API reference, checked again on 2026-11-12:
the endpoint answers 401 without a key, and the gateway lists `typesafe/jev-1.14` from TypeSafe. It is tested against a
local stand-in that answers in the reference's shape; no key was available, so it has never talked to Jev, and Jev's
accuracy here is unknown.

## What was measured

`tests/decide/evaluate.py` runs each backend in a process of its own on the same labelled items and writes every
decision, the accuracy per set and per language, the time per decision and the peak memory:

```bash
python3 src/decide/cli.py fetch multilingual     # about 0.7 GB, once
python3 tests/decide/evaluate.py --out /tmp/decide --backends rules,agent,laya:multilingual
python3 tests/decide/evaluate.py --out /tmp/decide --backends vega,vega:4b     # with the maker's package installed
```

The agent's answers are cached in that folder, so a rerun asks the model nothing. Measured on 2026-11-04 with Claude
Code as the agent, on 8 threads of a desktop CPU, with no fine-tuning of any checkpoint. Vega was measured on
2026-11-12 on the same sets and the same 8 threads, in a container with no network.

| Set | Task | Items | Rules | Pipeline today | Agent | Laya multilingual | Laya english | Laya typed-decisions | Vega 0.8B | Vega 4B |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Posting lines, English | `line_kind` | 34 | 0.71 | | 0.88 | 0.47 | 0.53 | 0.53 | 0.27 | 0.38 |
| Posting lines, Korean | `line_kind` | 22 | 0.73 | | 0.73 | 0.41 | 0.36 | 0.41 | 0.32 | 0.36 |
| Reviewed cover plan, English | `coverage` | 15 | 0.40 | 0.53 | 0.87 | 0.60 | 0.47 | 0.40 | 0.47 | 0.40 |
| Reviewed cover plan, Korean | `coverage` | 14 | 0.50 | 0.79 | 0.79 | 0.43 | 0.50 | 0.43 | 0.36 | 0.50 |
| Example kit against its answer key | `coverage` | 13 | 0.23 | 0.23 | 0.54 | 0.39 | 0.69 | 0.69 | 0.08 | 0.61 |
| Planted claim cases | `claim` | 23 | 1.00 | | 0.87 | 0.65 | 0.48 | 0.43 | 0.48 | 0.48 |
| Fictional claim cases | `claim` | 16 | 0.94 | | 1.00 | 0.38 | 0.44 | 0.44 | 0.50 | 0.50 |
| Fictional statement pairs, English | `contradiction` | 12 | 0.67 | | 1.00 | 0.83 | 0.75 | 0.58 | 0.50 | 0.67 |
| Fictional statement pairs, Korean | `contradiction` | 12 | 0.50 | | 1.00 | 0.67 | 0.67 | 0.75 | 0.58 | 0.58 |

The cells are accuracy. "Pipeline today" is what the existing step decides on the same line with more context than the
rules backend gets: the cover planner's word matching, and the interview audit's rating over the whole kit.

The example kit's row needs care. An answer key lists the gaps a person found, so a line it leaves out is not proven
covered, and accuracy rewards flagging little. Vega 4B's 0.61 there is that: it flagged 4 of the 13 lines, and not the
one gap the key names.

| Backend | Peak memory | Load | Posting line | Claim | Pair | Coverage line (4 evidence texts) |
|:---|---:|---:|---:|---:|---:|---:|
| `rules` | 24 MB | none | under 1 ms | under 1 ms | under 1 ms | under 1 ms |
| `laya`, multilingual | 2.6 GB | 7 s | 54 ms | 76 ms | 74 ms | 610 ms |
| `laya`, english | 3.1 GB | 7 s | 162 ms | 239 ms | 254 ms | 3.0 s |
| `laya`, typed-decisions | 3.1 GB | 7 s | 164 ms | 264 ms | 240 ms | 3.1 s |
| `agent`, one item per call | 135 MB | none | 4.3 s | 4.9 s | 4.3 s | 4.7 s |
| `agent`, in batches, per item | 135 MB | none | 287 ms | 581 ms | 400 ms | 780 ms |
| `vega`, 0.8B reader | 4.9 GB | 3 s | 482 ms | 447 ms | 424 ms | 1.1 s |
| `vega`, 4B reader | 24.6 GB | 8 s | 2.3 s | 2.8 s | 3.3 s | 7.0 s |

Times are medians. Both English checkpoints run in torch here. The `laya` default routing holds two checkpoints, 4.3 GB
at its peak. Vega reads a coverage line with all its evidence texts at once, and its loads are from files already on
the PC (the first download and load took 62 s for the 0.8B and 160 s for the 4B).

## The kit's search

The interview kit's search ranks its cards while a person types a question: by keywords in the page (BM25 over the
title, key line, phrasings and text, with Korean particles stripped and synonym groups), with a similarity model
(bge-m3) blended in when a person switches it on (`docs/INTERVIEW.md`). A decision model could take part in two ways:
pick the card that answers the question out of every card of the kit, or put the first three cards the search showed
in its own order.

The kit's own eval set asks with its cards' words, and the keywords alone put the right card first for all 15 of its
questions, so it leaves nothing to win. `tests/decide/fixtures/kit_questions_reworded.json` asks about the same 18
cards the way an interviewer might, with words the cards mostly do not use, 14 questions in English and 14 in Korean:

```bash
python3 src/interview/cli.py eval --job examples/interview/jobs/gamma-platform \
    --questions tests/decide/fixtures/kit_questions_reworded.json --out /tmp/kit/keywords
python3 tests/decide/kit_search.py --backend laya --runs keywords=/tmp/kit/keywords/eval.json
```

For the similarity run, `serve --model <bge-m3 folder>` with the switch on, and `eval --url` against it.

| Ranking | First card right | Right card in the first three |
|:---|---:|---:|
| Keywords (the default) | 16 of 28 | 22 of 28 |
| Keywords and bge-m3 (the switch) | 24 of 28 | 28 of 28 |
| Laya multilingual, picking out of all 18 cards | 3 of 28 | 10 of 28 |
| Vega 0.8B, picking out of all 18 cards | 7 of 28 | 11 of 28 |
| Vega 4B, picking out of all 18 cards | 7 of 28 | 13 of 28 |
| Laya, reordering the keywords' first three | 11 of 28 | 22 of 28 |
| Vega 0.8B, reordering the keywords' first three | 11 of 28 | 22 of 28 |
| Vega 4B, reordering the keywords' first three | 9 of 28 | 22 of 28 |
| Laya, reordering the similarity's first three | 10 of 28 | 28 of 28 |
| Vega 0.8B, reordering the similarity's first three | 13 of 28 | 28 of 28 |
| Vega 4B, reordering the similarity's first three | 12 of 28 | 28 of 28 |

Every decision model put the right card first less often than the search it was given. Picking out of all the cards,
each chose the same few cards whatever the question, as on the decision sets above: Laya put A2 or K1 first for 25 of
the 28 questions, Vega 0.8B put K2, R1 or R2 first for 22, and Vega 4B put A2 first for 17. A pick also took 0.4
seconds (Laya), 2.2 seconds (Vega 0.8B) or 12.5 seconds (Vega 4B) on 8 CPU threads, while the page answers as a person
types. The similarity model is the kind made for ranking, and it turns 16 of 28 into 24. The search keeps its keywords
and its optional similarity model; a decision model has no place in it.

What the measurement did change: the similarity model could be switched on from `serve --model` only, never in the
panel, where the kit is mostly read. `OFFEROWL_SEARCH_MODEL` now names its folder for both
([INTERVIEW.md](INTERVIEW.md#the-search-view-serve)), and the same 28 questions typed into the kit at the panel's
address, with the switch on, score the same 24 and 28.

The interview deck pairs each question of the question map with the script that answers it by the map's coverage rule
(`src/interview/cover.py`), the step the `coverage` rows above measure. The other rankings in Offerowl choose what
the agent reads: the evidence a scene or an application answer is written from. The agent then decides with all of it
in view, so a weaker model in between could only drop evidence.

## The verdict

A decision model takes over a step only where it comes within a few points of the agent, in Korean as well as English.

| Step | Today | Laya and Vega against the agent | Verdict |
|:---|:---|:---|:---|
| Kind of a posting line | The section heading, exactly, when there is one | Laya 0.53 and Vega 0.38 against 0.88 in English, 0.41 and 0.36 against 0.73 in Korean | Stays with the heading |
| Coverage of a posting line | Word matching, or the agent when one is on | Laya 0.60 and Vega 0.47 against 0.87 in English, 0.50 and 0.50 against 0.79 in Korean | Stays |
| Claim stronger than its evidence | `factcheck.claim_issues` | Laya 0.65 and Vega 0.48 against 0.87, and the rules score 1.00 | Stays with the rules |
| Two statements contradict | The audit's rules, then the agent | Laya 0.83 and Vega 0.67 against 1.00 in English, 0.75 and 0.58 against 1.00 in Korean | Stays |
| The kit's search (above) | Keywords, with similarity when it is switched on | Worse than the search each was given, both ways tried | Stays |

Each cell is the better variant of each model. No model passes on any step, so no step of Offerowl calls Laya, Vega
or Jev, and nothing about them is on by default.

Laya's maker says it is a base to specialise and not a zero-shot engine, and these numbers agree. Vega's 0.8B reader
gives nearly one answer per question whatever the item: requirement for 47 of 56 posting lines, weak for 38 of 42
coverage lines, supported for all 39 claims, contradiction for 21 of 24 pairs. The 4B reader spreads its answers more
and still calls no claim an overclaim. The route Vega marks `auto`, the one its maker says to gate on, held for 3 of
the 0.8B reader's 27 such answers and 2 of the 4B reader's 8, so it cannot pick out the answers to trust either. A
fine-tuned checkpoint, or Vega's heads fitted on labelled rows, may do better, but the labelled sets here are too
small to train on and still measure with, and fine-tuning needs a license check on the data.

The layer stays because it makes the next attempt cheap. Vega came out the day after the first measurement and
became one more backend of the same four questions, measured with the same command. For now `src/decide/` is a
measuring bench: the rules it calls are the ones the pipeline already uses, and no step goes through it.

Checked again on 2026-11-12. Laya's weights are the files measured here: since the measured revision (`7b928d8`,
2026-10-03) its maker's repository changed only its model card, to cite a preprint (`85cc74d`, 2026-11-09), and the
laya package's releases since (0.4.26 to 0.4.31) add integrations and routing, not checkpoints. Jev is at 1.14, the
client's default, and still unmeasured for want of a key. What would reopen the question: a checkpoint tuned, or
Vega's heads fitted, on labelled decisions of Offerowl's own kind and measured on sets it was not tuned on (the sets
above are too small to do both), or Jev measured on these fictional sets, and even then only as a backend a person
turns on, since its inputs leave the PC.
