# Closed networks

Offerowl runs on a PC or a cluster with no route to the internet, in each of its four ways. You bring the files across once. What needs a
maker's server cannot work there, and this page says which parts those are.

## What works and what does not

| | On a closed network |
|:---|:---|
| Panel, canvas, deck, plain resume, typesetting, every check, tracker, backup | Works, with nothing else to set up |
| Reading your files, writing the resume, letter and scripts, drawing figures | Works with [a model server inside the network](#a-model-inside-the-network). With none, you fill in the facts yourself, and an Offerowl profile file is still read |
| Search and practice in the interview kit | Works. A spoken answer needs faster-whisper and its model folder on that PC; without them you type the answer |
| OCR for scanned files and screenshots | In the container, and on Windows with its own OCR. On macOS and Linux it needs Tesseract installed |
| **Claude Code and Codex** | **Not possible.** They answer from their makers' servers. Use a model server, or no AI |
| **A posting's link** | **Not possible.** Paste the posting's text instead |
| **Building the image, `npm ci`, downloading a release** | **Not possible on the closed side.** Do them on a connected PC and carry the result |
| Updates | Offerowl never looks for updates. Carry the new files across the same way. A [backup](README.md#9-your-files) moves your work |

## What to carry

| Way | Files | Also needed on the closed side |
|:---|:---|:---|
| The app | `Offerowl-<system>-<machine>`, about 55 MB | Edge, Chrome or Chromium, for PDFs |
| A container | the image as one compressed file, about 600 MB (about 1.5 GB once loaded), and `deploy/docker/compose.yaml` | Docker with Compose |
| A Helm chart | the image, and `offerowl-<version>.tgz` | a registry the cluster pulls from. The chart needs this one image and no other, its test pod included |
| The Python package | the wheel, Pillow and pypdfium2, and `node_modules`, for the same system, machine and Python version | Python 3.10 or newer, Node.js 22 or newer, Edge, Chrome or Chromium |

Check the files against the release's `SHA256SUMS` before you carry them across, as [installing](INSTALL.md#1-the-desktop-app)
shows.

## The app

Copy the file and start it ([installing](INSTALL.md#1-the-desktop-app)). Turn the agent's switch off, or set **AI agent** to
**Local model** in **Settings**. With no agent, a dropped Offerowl profile file still becomes PDFs.

## A container

On a connected PC:

```bash
docker pull ghcr.io/kanggu12/offerowl-app:0.9.0
docker save ghcr.io/kanggu12/offerowl-app:0.9.0 | gzip > offerowl-app-0.9.0.tar.gz
```

Carry that file and `deploy/docker/compose.yaml`. On the closed side:

```bash
docker load -i offerowl-app-0.9.0.tar.gz
OFFEROWL_APP_IMAGE=ghcr.io/kanggu12/offerowl-app OFFEROWL_APP_TAG=0.9.0 \
  docker compose -f compose.yaml up -d --no-build --pull never
```

Then open http://127.0.0.1:8797 in a browser on that PC.

## A Helm chart

On a connected PC, save the image as above and fetch the chart:

```bash
helm pull oci://ghcr.io/kanggu12/charts/offerowl --version 0.9.0
```

On the closed side, push the image to your registry and install from the file:

```bash
docker load -i offerowl-app-0.9.0.tar.gz
docker tag ghcr.io/kanggu12/offerowl-app:0.9.0 registry.internal/offerowl-app:0.9.0
docker push registry.internal/offerowl-app:0.9.0

helm install offerowl ./offerowl-0.9.0.tgz --namespace offerowl --create-namespace \
  --set image.repository=registry.internal/offerowl-app --set image.tag=0.9.0 \
  --set ai.backend=openai-compat --set ai.url=http://models.internal:11434 --set ai.model=<model name>
```

A registry that asks for a login takes `--set 'imagePullSecrets[0].name=<secret>'`.

## The Python package

On a connected PC with the same system, machine and Python version (Pillow's wheels are made for one Python version), from a
checkout of the release's tag:

```bash
mkdir carry
cp offerowl-0.9.0-py3-none-any.whl carry/       # from the Releases page
pip download "pillow==13.0.0; python_version >= '3.11'" "pillow==12.3.0; python_version < '3.11'" "pypdfium2==5.14.0" -d carry   # the versions the release was tested with
npm ci --omit=dev && tar -czf carry/node_modules.tar.gz node_modules
```

Carry the folder. On the closed side:

```bash
python3 -m venv ~/offerowl-venv
~/offerowl-venv/bin/pip install --no-index --find-links carry offerowl "pillow==13.0.0; python_version >= '3.11'" "pillow==12.3.0; python_version < '3.11'" "pypdfium2==5.14.0"
ENGINE=$(~/offerowl-venv/bin/python -c 'import offerowl, os; print(os.path.dirname(offerowl.__file__))')/engine
tar -xzf carry/node_modules.tar.gz -C "$ENGINE"
export OFFEROWL_RENDERER=html
~/offerowl-venv/bin/offerowl doctor
~/offerowl-venv/bin/offerowl panel --open
```

Keep `OFFEROWL_RENDERER=html` in every shell that starts Offerowl there (your shell's profile): on a PC with Docker the package
otherwise typesets in the render container, whose image is built with the network.

## A model inside the network

Any server with an OpenAI-compatible address works: Ollama, vLLM, LM Studio. Fetch the model on a connected PC and carry it with the server: Ollama
keeps its models in `~/.ollama/models`, and vLLM takes a model's folder.

- **The app and the Python package:** in **Settings**, set **AI agent** to **Local model** and type the address and the model's name. Or set
  `OFFEROWL_LLM=openai-compat`, `OFFEROWL_LLM_URL` and `OFFEROWL_LLM_MODEL` before starting.
- **A container:** set the same three in the shell or in a `.env` file beside the `compose.yaml` you carried.
- **A Helm chart:** `ai.backend`, `ai.url` and `ai.model`, as above.

If your PC sets `HTTP_PROXY`, add the server's name to `NO_PROXY`. The checks are the same for any model: what the evidence does not hold is
stopped or left out, so a weaker model leaves you with fewer sentences, not with wrong ones. The numbers in the README were measured with Claude
Code, not with a local model.

## How this was checked

On 2026-11-05, on Linux (the first check also runs in CI on every push to main and every pull request: ci.yml, job
`app-image`):

- `tests/packaging/offline_e2e.sh` ran the image with no network at all: the example, a pasted posting, the resume written by a stand-in model
  server, the deck, the PDFs, the plain resume, the question map and the interview view.
- The image went through `docker save` and `docker load`, and `compose.yaml` alone in a folder started it with `--no-build --pull never`.
- The app's end-to-end test passed in a network namespace with loopback only.
- The package installed with `--no-index`, and its self-test passed the same way.

Not run: the app on Windows and macOS with the network cut, a real model server, and the chart against an internal registry. The chart was
installed from an image loaded on the node, and the commands above were rendered with `helm template`.
