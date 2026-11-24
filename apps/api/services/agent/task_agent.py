"""Tasks' part for the agent (apps/api/tasks.py inherits it): which backend a model task talks to, pointed at before each
call (src/llm.py reads the environment per call), the stand-in agent started when the tests ask for it, and the state of
the run from files to documents (its stop and the request that waits for it)."""
from __future__ import annotations

import os  # the environment src/llm.py reads
import threading  # the run's stop


class AgentTasks:
    """The agent a model task talks to, and the autopilot's stop and queue."""

    def __init__(self):
        super().__init__()  # the other parts' own
        self.standin = None  # the stand-in server, started when the stand-in backend is used
        # what the person's environment said at the start: a local model's address and name are set here while one is in use,
        # and these come back when another backend is chosen (codex takes OFFEROWL_LLM_MODEL as its -m)
        self.env0 = {k: os.environ.get(k) for k in ("OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL")}
        self.autopilot_stop = threading.Event()  # the person asked a run of autopilot.py to stop
        self.autopilot_next = None  # a run asked for while one ran: it starts when that one ends (autopilot.chain)

    def backend(self) -> str:
        """Point src/llm.py at the backend in use and return the name its run() takes ('none' when off)."""
        name = self.card.chosen()  # from the settings
        s = self.card.settings_fn()  # the settings
        if name == "standin":  # tests and the app's check: the stand-in as an OpenAI-compatible server
            if self.standin is None:  # started once, reused after
                from .standin import serve  # only now: the stand-in agent, this service's own
                self.standin = serve(0)  # a free port
            os.environ["OFFEROWL_LLM_URL"] = f"http://127.0.0.1:{self.standin.server_address[1]}"  # llm.py reads it per call
            os.environ["OFFEROWL_LLM_MODEL"] = "standin"  # the model name the stand-in ignores
            name = "openai-compat"  # llm.py reaches the stand-in this way
        elif name == "openai-compat":  # a local model server
            os.environ["OFFEROWL_LLM_URL"] = s.get("llm_url", "")  # the address from the menu
            os.environ["OFFEROWL_LLM_MODEL"] = s.get("llm_model", "") or "default"  # a name is required by the request
        else:  # an agent CLI, or none: the local model's values go, and what the start was given comes back
            for k, v in self.env0.items():
                if v is None:
                    os.environ.pop(k, None)  # not set at the start
                else:
                    os.environ[k] = v  # set at the start, by the person
        os.environ["OFFEROWL_LLM"] = name  # draft.py's calls take no backend argument; the OFFEROWL_ name wins in llm.py
        return name  # what ingest.extract takes
