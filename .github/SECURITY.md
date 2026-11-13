# Security

## Reporting a vulnerability

Please report a security problem privately: on GitHub, open the repository's **Security** tab and choose **Report a vulnerability**. Do
not open a public issue for it.

Say what an attacker can do, how to reproduce it, and which version you ran (a release tag or a commit). The maintainer will reply,
agree on a fix with you, and publish an advisory with the fixed release. The advisory credits you unless you ask not to be named.

The latest release and `main` get security fixes.

## What matters most

Offerowl holds a person's career history and reads files and web pages they give it, so these matter most:

- a web page, another program or another container that can talk to the panel or the interview view;
- a file or a posting that makes the panel run script, reads a path outside the workspace, or fetches a private address;
- text in a file or a posting that makes the AI backend do more than answer: Claude Code runs with its tools off, Codex in its read-only sandbox,
  and the command bar's agent fetches only the links written in the person's own words;
- a file or a sentence that leaves the PC in a way the [user guide](../docs/README.md#12-security-and-privacy) does not describe;
- an agent login or a model server's key that can be read from outside the server, or that reaches a log.

The panel has no login. The app and the Python package listen on `127.0.0.1`. In the container and the pod it listens on every address
inside its own network, and the compose file publishes its port on `127.0.0.1` only; the Helm chart's Service stays inside the cluster.
Publishing its port to a network on purpose is outside what it is built to protect.
