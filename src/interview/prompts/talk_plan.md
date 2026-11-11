You write, in {{language}}, the career plan slide of a job-interview talk: what the person will do in this job, in three phases. The interviewers asked for this: {{request}}. A plan is the person's intention, so its items need no evidence; but every word on what the person has done before rests on the evidence, and the plan's tools and practices come from the posting or the person's record. Make it concrete: what each phase delivers and how its success is measured.

{{target}}

{{rules}}

What to write, under "plan":
- "lede": one or two sentences of at most {{lede}}: the goal of the plan, from the posting's own words.
- "phases": three phases in order, each {"when" (a span such as the first three months, at most {{when}}), "title" (at most {{head}}), "basis" (what the phase decides by, at most {{head}}), "items" (three lines of at most {{item}}), "output" (what it leaves behind, at most {{item}}), "metric" (how success is measured, at most {{item}}), "box" ({"title": at most {{head}}, "items": three short lines})}.
- "gaps": one line of at most {{lede}} naming what the person has not done yet that the posting asks for, said plainly; "" when nothing is missing.
- "ev": the evidence of any word about the person's past.
- {{style_line}}

Company notes (facts about the company, from the posting and the person's own research):
{{company}}

Evidence (id, then text):
{{evidence}}

Return JSON only, in this shape:
{"plan": {"lede": "...", "phases": [{"when": "...", "title": "...", "basis": "...", "items": ["..."], "output": "...", "metric": "...", "box": {"title": "...", "items": ["..."]}}], "gaps": "...", "ev": ["id"]}}
