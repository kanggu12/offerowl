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
the label, a confidence (the label's probability, or none for the rules and a stated one for the agent), the scores
per label, the backend, and the milliseconds the decision took.

| Backend | What answers | Where the inputs go | Needs |
|---|---|---|---|
| `rules` (default) | the rule checks Offerowl already has | nowhere | nothing |
| `agent` | the AI backend of `src/llm.py`, asked for typed JSON under a schema, many items per call | where that backend is (a signed-in CLI sends them to its provider; a local server keeps them) | the backend |
| `laya` | Laya, a decision model run on this PC's CPU | nowhere | the model files (below), numpy and tokenizers, and onnxruntime or torch |
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

## Jev

Jev is a closed, hosted decision model. `src/decide/jev.py` sends one System One request per decision
(`POST <url>/v1/systemone` with the model name, the state as a list of strings, and the same typed question Laya
gets) and reads the chosen option and its probabilities. It is off unless both settings are given:

| Setting | Meaning |
|---|---|
| `OFFEROWL_JEV_KEY` | the gateway key |
| `OFFEROWL_JEV_SEND=1` | consent that decision inputs (posting lines, evidence, sentences) leave this PC |
| `OFFEROWL_JEV_URL` | the gateway (default `https://openrouter.ai/api`; the maker's own endpoint is `https://api.typesafe.ai`) |
| `OFFEROWL_JEV_MODEL` | the model name (default `typesafe/jev-1.14`) |

Only the task's fields leave the PC, never an item's id or other keys. The list command and `decide.backend_info()`
always show where the inputs would go. The client was written from the gateway's documentation and tested against a
local stand-in only: no key was available, so it has never talked to Jev, and Jev's accuracy here is unknown.

## What was measured

`tests/decide/evaluate.py` runs each backend in a process of its own on the same labelled items and writes every
decision, the accuracy per set and per language, the time per decision and the peak memory:

```bash
python3 src/decide/cli.py fetch multilingual     # about 0.7 GB, once
python3 tests/decide/evaluate.py --out /tmp/decide --backends rules,agent,laya:multilingual
```

The agent's answers are cached in that folder, so a rerun asks the model nothing. Measured on 2026-11-04 with Claude
Code as the agent, on 8 threads of a desktop CPU, with no fine-tuning of any checkpoint.

| Set | Task | Items | Rules | Pipeline today | Agent | Laya multilingual | Laya english | Laya typed-decisions |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|
| Posting lines, English | `line_kind` | 34 | 0.71 | | 0.88 | 0.47 | 0.53 | 0.53 |
| Posting lines, Korean | `line_kind` | 22 | 0.73 | | 0.73 | 0.41 | 0.36 | 0.41 |
| Reviewed cover plan, English | `coverage` | 15 | 0.40 | 0.53 | 0.87 | 0.60 | 0.47 | 0.40 |
| Reviewed cover plan, Korean | `coverage` | 14 | 0.50 | 0.79 | 0.79 | 0.43 | 0.50 | 0.43 |
| Example kit against its answer key | `coverage` | 13 | 0.23 | 0.23 | 0.54 | 0.39 | 0.69 | 0.69 |
| Planted claim cases | `claim` | 23 | 1.00 | | 0.87 | 0.65 | 0.48 | 0.43 |
| Fictional claim cases | `claim` | 16 | 0.94 | | 1.00 | 0.38 | 0.44 | 0.44 |
| Fictional statement pairs, English | `contradiction` | 12 | 0.67 | | 1.00 | 0.83 | 0.75 | 0.58 |
| Fictional statement pairs, Korean | `contradiction` | 12 | 0.50 | | 1.00 | 0.67 | 0.67 | 0.75 |

The cells are accuracy. "Pipeline today" is what the existing step decides on the same line with more context than the
rules backend gets: the cover planner's word matching, and the interview audit's rating over the whole kit.

The example kit's row needs care. An answer key lists the gaps a person found, so a line it leaves out is not proven
covered, and accuracy rewards flagging little.

| Backend | Peak memory | Load | Posting line | Claim | Pair | Coverage line (4 evidence texts) |
|:---|---:|---:|---:|---:|---:|---:|
| `rules` | 24 MB | none | under 1 ms | under 1 ms | under 1 ms | under 1 ms |
| `laya`, multilingual | 2.6 GB | 7 s | 54 ms | 76 ms | 74 ms | 610 ms |
| `laya`, english | 3.1 GB | 7 s | 162 ms | 239 ms | 254 ms | 3.0 s |
| `laya`, typed-decisions | 3.1 GB | 7 s | 164 ms | 264 ms | 240 ms | 3.1 s |
| `agent`, one item per call | 135 MB | none | 4.3 s | 4.9 s | 4.3 s | 4.7 s |
| `agent`, in batches, per item | 135 MB | none | 287 ms | 581 ms | 400 ms | 780 ms |

Times are medians. Both English checkpoints run in torch here. The `laya` default routing holds two checkpoints, 4.3 GB
at its peak.

## The verdict

A decision model takes over a step only where it comes within a few points of the agent, in Korean as well as English.

| Step | Today | Laya against the agent | Verdict |
|:---|:---|:---|:---|
| Kind of a posting line | The section heading, exactly, when there is one | 0.53 against 0.88 in English, 0.41 against 0.73 in Korean | Stays with the heading |
| Coverage of a posting line | Word matching, or the agent when one is on | 0.60 against 0.87 in English, 0.50 against 0.79 in Korean | Stays |
| Claim stronger than its evidence | `factcheck.claim_issues` | 0.65 against 0.87, and the rules score 1.00 | Stays with the rules |
| Two statements contradict | The audit's rules, then the agent | 0.83 against 1.00 in English, 0.75 against 1.00 in Korean | Stays |

No checkpoint passes on any step, so no step of Offerowl calls Laya or Jev, and nothing about them is on by default.
Its maker says Laya is a base to specialise and not a zero-shot engine, and these numbers agree. A fine-tuned checkpoint
may do better, but the labelled sets here are too small to train on and still measure with, and fine-tuning needs a
license check on the data.

The layer stays because it makes the next attempt cheap. A new model becomes one more backend of the same four
questions, and this page's tables come from one command. For now `src/decide/` is a measuring bench: the rules it calls
are the ones the pipeline already uses, and no step goes through it.
