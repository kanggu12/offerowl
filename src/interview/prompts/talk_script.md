You write what one person says over each slide of a talk in a job interview, in {{language}}, as they would say it aloud: {{spoken}}. The interviewers asked for this: {{request}}. Each slide has its time; its words should fill about that time at the pace given for it. A portfolio page is the person's own slide: say what it shows and why it matters, in more words than the slide has, never by reading it out.

{{rules}}

For each slide below, write:
- "lines": the sentences to say, in order. Each {"text": one sentence, "ev": the evidence it rests on}. A sentence that only leads from one slide to the next, or says what the slide is about, and states no fact of the person's record may have "ev": []. Every fact, number, name and tool comes from the evidence it cites.
- "cue": where on the slide to point while speaking, in a few words, or "".
- "short": the one sentence to say instead of the lines when time runs short, or "" for a slide that is never cut.
- "questions": one or two questions an interviewer may ask about this slide (none for the cover, the agenda, a divider and the end), each {"q": the question as asked, "a": what backs the answer, in one or two sentences, "ev": the evidence}. When the evidence does not hold the answer, "a" says so plainly, so the person answers from memory and invents nothing.
- Never write a page number.
- {{style_line}}

The slides (key | seconds | about how long to speak | what the slide shows):
{{slides}}

Evidence (id, then text):
{{evidence}}

Return JSON only, in this shape:
{"slides": [{"key": "...", "lines": [{"text": "...", "ev": ["id"]}], "cue": "...", "short": "...", "questions": [{"q": "...", "a": "...", "ev": ["id"]}]}]}
