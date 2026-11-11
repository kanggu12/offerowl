You write, in {{language}}, the three slides of a job-interview talk that tell the hardest problem the person solved: the problem, the way through and what came of it. The interviewers asked for this: {{request}}. The story is the project below; its blocks are the evidence. Tell it as it happened: who wanted what, what stood in the way, what the person did with whom, what was measured or decided, and what the person learned. Keep the person's part exactly as the evidence gives it, and say what already existed before them.

{{rules}}

What to write, each slide with "title" (a few words), "sub" (the project or the conflict in a line of at most {{sub}}), "lede" (one or two sentences of at most {{lede}}, with one ==highlight== of the key phrase) and "ev":
- "problem": also "sides", the two positions that met (each {"title": whose position, "items": two to four boxes, each {"title": at most {{box}}, "sub": at most {{box}}}}); "question", the open question both positions left, in a line of at most {{lede}}; "cards", three or four numbered cards {"title", "text" of at most {{card}}, "ev"} on the situation; "scope", one sentence on what was there before and what the person's own part was, with "ev".
- "approach": also "steps", three to five steps in order (each {"title": at most {{box}}, "sub": at most {{box}}}); "cards", three or four cards {"title", "text", "ev"} on what was done and why.
- "result": also "cards", three or four cards {"title", "text", "ev"}: the outcome, one or two things learned, and what the person would carry into the next job.
- Never write a page number in a text.
- {{style_line}}

The project: {{project}}

Evidence (id, then text):
{{evidence}}

Return JSON only, in this shape:
{"problem": {"title": "...", "sub": "...", "lede": "...", "ev": ["id"], "sides": [{"title": "...", "items": [{"title": "...", "sub": "..."}]}], "question": "...", "cards": [{"title": "...", "text": "...", "ev": ["id"]}], "scope": {"text": "...", "ev": ["id"]}}, "approach": {"title": "...", "sub": "...", "lede": "...", "ev": ["id"], "steps": [{"title": "...", "sub": "..."}], "cards": [{"title": "...", "text": "...", "ev": ["id"]}]}, "result": {"title": "...", "sub": "...", "lede": "...", "ev": ["id"], "cards": [{"title": "...", "text": "...", "ev": ["id"]}]}}
