You write the framing words of a talk one person gives in a job interview, in {{language}}: the three messages the talk proves and the opening of each of its parts. The interviewers asked for this: {{request}}. The talk runs about {{minutes}} minutes. Its slides are listed below with their keys; the person's record is the evidence.

{{target}}

{{rules}}

What to write:
- "messages": three messages the whole talk proves, strongest first. Each has "title" (a noun phrase of at most {{msg_title}}), "text" (one sentence: where it happened and what came of it, at most {{msg_text}}), "ev" (the evidence it rests on) and "slides" (the keys of the slides that show it, one to three). The three must not repeat one another.
- "parts": one for each part listed below, {"part": its number, "what": what the part covers in one line of at most {{what}}, "core": the part's one point in a line of at most {{core}}, "lead": one or two sentences of at most {{lead}} that open the part and follow from the part before it, "ev": the evidence of "lead" and "core"}. The first part's lead says who the person is; the lead of a part about the future may say what the person wants, without evidence for the wish itself.
- Never write a page number in a text: a slide is named only by its key, in "slides".
- {{style_line}}

The parts (number | title | what the interviewers asked):
{{parts}}

The slides (key | part | kind | title | what it shows):
{{slides}}

Evidence (id, then text):
{{evidence}}

Return JSON only, in this shape:
{"messages": [{"title": "...", "text": "...", "ev": ["id"], "slides": ["key"]}], "parts": [{"part": 1, "what": "...", "core": "...", "lead": "...", "ev": ["id"]}]}
