You compare a job candidate's interview scripts with the documents the candidate already submitted, and with what
the candidate says in other scenes. The interviewer has the documents, so every spoken answer must agree with them,
and two answers must not tell the same fact two ways.

For each scene below, find the places where the candidate's English answer disagrees with a document or with another
scene:
- a different number, count, date, month, year or period for the same thing ("early 2024" and "2024.05" disagree;
  "September 2021" and "2021.08" disagree), or work placed outside the period the document gives it (a plan written in
  2023 for a project the document ends in 2022);
- a different title or role ("development lead" and "Team Lead" disagree);
- a different scope: the answer says "I" built, founded, led or ported it where the document or another scene gives
  it to the team or a colleague, or the answer says it already existed, was a colleague's, was only touched or stayed a
  proposal where the document or another scene claims the candidate designed, built, ran or did it;
- a claim the document states differently ("proposed" and "built"; "a move" and "built on site"; "not in my records"
  and a document that names it);
- a different place, customer, project, product or tool for the same thing;
- a reason or answer that another scene gives differently.
Do not flag things the documents simply do not mention, style, or wording that means the same. Most scenes have no
disagreement; flag at most five per scene, the clearest first.

Every flag must quote, word for word, a short part of the answer (scene_quote) and a short part of the document or of
the other scene (doc_quote) that disagree. Quote exactly: the quotes are checked against the texts, and a flag whose
quotes are not found is dropped. Keep each quote under 20 words. doc is "resume", "portfolio", or "scene <id>" for
another scene.

Return only JSON:
{{"flags": [{{"id": "scene id", "scene_quote": "...", "doc": "resume, portfolio or scene <id>", "doc_quote": "...",
             "kind": "number, date, title, scope, claim, name or scene", "why": "one short sentence"}}]}}
Return {{"flags": []}} when everything agrees.

{scenes}
