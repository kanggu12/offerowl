You write, in {{language}}, the slide of a job-interview talk that says why the person wants this job. The interviewers asked for this: {{request}}. It is a slide of a talk, not a checklist: give the person's reasons, from their record and the posting's own words. The company's words come only from the posting and the company notes below.

{{target}}

{{rules}}

What to write, under "why":
- "lede": why this job, one or two sentences of at most {{lede}}, with its "ev" when it speaks of the person's record.
- "cards": three cards {"title", "text", "ev"}: this job as the posting describes it, the company now as the company notes say, and what the person wants to do there.
- "close": one sentence the person wants the interviewers to remember.
- Never write a page number in a text. Never list the posting's lines against the record: the slide gives reasons, not a checklist.
- {{style_line}}

Posting lines (number | kind | text):
{{posting}}

Company notes (facts about the company, from the posting and the person's own research; never facts about the person):
{{company}}

Evidence (id, then text):
{{evidence}}

Return JSON only, in this shape:
{"why": {"lede": "...", "ev": ["id"], "cards": [{"title": "...", "text": "...", "ev": ["id"]}], "close": "..."}}
