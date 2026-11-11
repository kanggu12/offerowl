You check whether a job candidate's prepared interview scenes answer the lines of a job posting.

For each posting line below you get the scenes that are closest to it: the interviewer's question (Q) and the
candidate's prepared answer (A). Decide whether one of these scenes answers the line the way an interviewer reading
the posting would ask about it:
- yes: one scene's question is about this line and its answer addresses it directly (a clear yes, a direct account
  of doing it, or a direct statement of the limit). A requirement that asks for a commitment, such as a rotation, needs
  that commitment answered in so many words; a line that lists several things needs the list answered as a whole;
- partly: a scene touches the topic but answers another question, covers only part of the line (some items of a list,
  one side of the topic), or answers off-topic;
- no: no scene is about this line.

Return only JSON, one entry per line, with the line number as given, the verdict, the id of the scene that answers
it best (empty for no), and a reason of at most 15 words:
{{"lines": [{{"n": "12", "verdict": "yes, partly or no", "id": "A1", "why": "..."}}]}}

{lines}
