You are an experienced technical interviewer preparing to interview a candidate for the job below. List the questions
you would really ask about the work itself, the ones a list of resume lines would never show.

## The job posting
{posting}

## The candidate's resume
{resume}

## What to list
- {count} questions in all.
- About half are "scenario": something goes wrong or a situation comes up in this job, and you ask what the candidate
  does ("A customer says their training got 30% slower than last week. What do you do?"). Draw them from the posting's
  duties, and make them concrete.
- About half are "technical": how something works, how to debug it, or the difference between two things this job uses
  ("A Kubernetes node shows NotReady. What do you check?", "What is the difference between SRE and DevOps?"). Draw them
  from the tools and duties in the posting and the resume.
- Each question is short spoken English, as said aloud, with a natural Korean translation.
- No behavioral questions, no questions about the company, and no questions about one line of the resume: other parts
  of the kit cover those.
- No two questions ask the same thing.

## Answer
Return only JSON:
{{"questions": [{{"kind": "scenario", "en": "...", "ko": "..."}}, {{"kind": "technical", "en": "...", "ko": "..."}}]}}
