"""The agent service: which AI backend Offerowl uses and whether it is signed in (the agent card), the command bar that
hands the person's words to that agent with Offerowl's own tools, the one run from the person's files to finished
documents (the autopilot), and the stand-in agent the tests and the desktop app's check use instead of a model.

Owns: ask/ (the command bar's asks and answers), out/runs.json (the finished runs) and the agent card (in memory, from
the CLIs' own answers: no CLI's files are ever opened).

    routes.py     its endpoints: each path or pattern with its handler (the gateway gathers them)
    agent.py      the agent card, and the day's calls counted from src/llm.py's call log
    ask.py        the command bar: one ask to Claude Code or Codex with Offerowl's MCP server as its tools
    autopilot.py  the run from files to documents, made of the other services' own steps
    standin.py    the stand-in agent: an OpenAI-compatible server, or the `claude` CLI, answering with fixed rules
    task_agent.py Tasks' part: the backend a model task talks to, and the run's stop and queue

Offers: AgentCard, BACKENDS and calls_summary (the card, built by the composition root, and the day's calls);
mcp_server (the MCP server the command bar and the desktop app hand an agent); finished_runs and forget_runs (the
autopilot's finished runs, as the state lists them and as a job deleted for good leaves them); AgentTasks, the part of
the tasks that adds backend() to the runner. The card counts the day's calls itself (AgentCard.calls).
"""
from .agent import BACKENDS, AgentCard, calls_summary  # noqa: F401  the card
from .ask import mcp_server  # noqa: F401  the MCP server an agent is handed
from .autopilot import forget_job as forget_runs, runs as finished_runs  # noqa: F401  the autopilot's finished runs
from .task_agent import AgentTasks  # noqa: F401  the agent's part of the tasks
from .routes import GET as GET_ROUTES, POST as POST_ROUTES, UPLOADS as UPLOAD_ROUTES  # noqa: F401  its endpoints, which the gateway gathers
