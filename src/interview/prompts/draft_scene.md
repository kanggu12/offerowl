You write one interview scene for a Korean candidate who will answer in English. The candidate will say these lines
aloud, so they must sound like natural speech, say only what is true, and go deep enough that the candidate is ready
for the follow-ups too.

## The question
Kind: {kind}
Planned question: {question}
It comes from: {source}

## Evidence about the candidate
{evidence}

## What to write
{depth}
- The first line is the interviewer asking the planned question as given, since this is the question the candidate is
  practising. The first sentence of the first answer answers it: a yes-or-no question starts with yes or no, and any
  other question starts with the conclusion, not with background.
- Every line comes as a pair: the English line, then its Korean translation ("해석"), a full and natural Korean
  translation with the same facts in the same order.
- The interviewer's lines ("면접관") are short and natural. Each follow-up grows out of what the candidate just said:
  why that choice, what exactly they did, what happened next, what if it had not worked, which part was theirs. No
  follow-up repeats an earlier question.
- Each answer stays on the question. An answer does not end on a line of career added for its own sake or on a slogan;
  when the candidate's own work comes in, it comes in as the example of the point being made.

## Facts
- What the candidate did comes only from the evidence: numbers, dates, names, tools, results and scope exactly as the
  evidence gives them. Never invent a number, a name, a date, a tool, a team size, a customer or a result of theirs.
- Team work stays the team's; a proposal stays a proposal in every tense ("I designed and proposed it", never "it runs"
  or "it is switched on"); a calculation stays a calculation. A measured number keeps its conditions, and two
  measurements are never merged into one.
- How things work is not a fact about the candidate. Use your own knowledge of tools, commands, flags, states, error
  names and common causes, exactly and correctly. Write it as what one does or what a tool does, in the present tense
  ("`sinfo -R` shows why a node is drained", "I check the link counters first"). Never put it in the past tense and
  never attach it to a company or a project, unless the evidence says so. Use "In general" at most once in a scene, for
  a longer explanation; a plain statement of how a tool works needs no label.
- The evidence is a selection, not everything the candidate has done. Never say they have not done, not used or have
  no experience with something, unless the evidence says so in those words, or the question asks it directly and
  nothing in the evidence mentions it; then say so plainly in the first sentence ("No, not yet."), give the closest
  thing the evidence shows, and say in the caution what to correct if the candidate has done more. In any other case
  where the evidence does not show it, give the approach in the present tense and add the closest thing it does show.
- The caution names a follow-up the interviewer may ask and what to have ready for it. You see only a selection of the
  evidence, so the caution never says the materials lack something, never asks the candidate to fill in from memory what
  may already be on record, and never tells the candidate not to say something unless the evidence says it was not so.

## Speech marks in the candidate's English lines
- ` / ` marks a breath every 4 to 8 words, where a speaker would naturally pause, never inside a phrase ("whether a
  remap / is pending" is wrong).
- ` // ` goes between sentences inside a line, never at the start or the end of a line.
- Mark 1 or 2 key words per sentence as **stress** (bold). When most words are bold, none of them stand out.
- Use exactly one ==key phrase== in the whole scene.
- Commands, flags and settings go in `backticks`, and no speech mark goes inside backticks. A query that needs `==` or
  `**` is said in words instead.
- A Korean stage note such as (웃으며) or (잠깐 쉬고) may appear once.

## Words
- The candidate's spoken English is limited, and every line has to be easy to say: common verbs, short phrases, one idea
  in a sentence, no idioms, no rare words that are hard to pronounce.
- An answer names at most two commands, in their short form; say the rest in words ("then I check the link counters").
  Never read out a long command with its flags or a list of field names: nobody says those aloud.
- Keep one vendor's tools together: NCCL and nvidia-smi with NVIDIA GPUs, RCCL and rocm-smi with AMD ones.
- Technical terms and proper nouns exactly as the evidence writes them, or as the tool itself writes them. In an English
  line, a company, school or team name takes its spelling from the [English names] block when it is there; otherwise keep
  the evidence's own spelling. Never make up a romanization of a name.
- Never use these words: {banned}.
- Never use these forms: {forbidden}.
- No padding ("Great question", "Let me explain"), no closing summary that repeats the answer.
- In the Korean translation, attach particles directly to Latin words and numbers (Kubernetes로, 2023년), and use no
  em dash, middle dot or arrows. Never call the candidate 당신. Translate every English word that has a usual Korean
  word; technical names stay as they are.

## Answer
Return only JSON:
{{"title_ko": "short Korean title", "title_en": "the question in English",
  "key": "the one line to land, in Korean",
  "lines": [["면접관", "..."], ["해석", "..."], ["나", "..."], ["해석", "..."]],
  "caution": "a short Korean note for the candidate, or an empty string"}}
The first line is the interviewer's. Each 면접관 and 나 line is followed by its 해석 line.
