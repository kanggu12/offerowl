# -*- coding: utf-8 -*-
"""Laya, a small decision model that runs on this PC, as a decision backend.

Laya (Apache 2.0 weights) reads a state and a typed question and scores every option of the question in one forward
pass of a bidirectional encoder. It never writes text. Three checkpoints are published:

  english          ModernBERT-large, 421M parameters, 512 tokens, English only
  multilingual     mmBERT-base, 322M parameters, 1024 tokens, about 100 languages (Korean included)
  typed-decisions  the English one tuned on its maker's own typed-decision benchmark, 1024 tokens

and a third-party ONNX export of the English checkpoint in FP32 and INT8. This module reads the published files
itself: the sequence layout and the decision head below follow the published model code, so no downloaded code ever
runs. The ONNX path needs onnxruntime, tokenizers and numpy; the other checkpoints need torch, transformers and
safetensors as well.

Settings:
  OFFEROWL_LAYA_DIR       folder that holds the downloaded files (default ~/.cache/offerowl/laya)
  OFFEROWL_LAYA_MODEL     auto (default), or one variant of VARIANTS below for every item
  OFFEROWL_LAYA_EN        the variant auto uses for text without Hangul (default: the first of EN_ORDER on disk)
  OFFEROWL_LAYA_THREADS   CPU threads (default 4)
  OFFEROWL_LAYA_DOWNLOAD  1 lets a missing variant download once; without it only files on this PC are used

`python3 src/decide/cli.py fetch <variant>` downloads a variant on purpose, checked against pinned hashes.
"""
import hashlib  # check downloaded files against the pinned hashes
import json  # configs and the serialized state
import math  # softmax without numpy for small rows
import os  # settings and CPU count
import pathlib  # paths
import re  # Hangul test
import resource  # peak memory of this process
import shutil  # move a finished download into place
import tempfile  # a partial download never sits under the final name
import threading  # one load at a time when two callers ask together
import time  # load and run times
import urllib.request  # the download

# The published repositories, pinned to the revisions that were measured, so a later upload cannot change the model
# under the same name without a new hash here
LAYA = ("convaiinnovations/laya", "7b928d828b7b0e022f929d9bd2e44165aa270148")  # the maker's repository: three checkpoints
LAYA_ONNX = ("tozp/laya-onnx", "0d1f7ebf46a3ea04ec4424df602f96ddefb66766")  # a third party's ONNX export of the English one
HUB = "https://huggingface.co"  # where both repositories live
# sha256 of every large file; the small JSON and tokenizer files are read as data and need no pin to be safe
SHA256 = {
    "model.safetensors": "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c",  # english
    "multilingual/model.safetensors": "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204",  # multilingual
    "multilingual/tokenizer/tokenizer.json": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",  # its 256k vocabulary
    "typed-decisions/model.safetensors": "4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e",  # typed-decisions
    "model.onnx": "053ee547e0c67d43574e1f8c9f4fc4ff1e1f6fc48bf7c4de1b848a1d275bcbf1",  # ONNX export, FP32
    "model_int8.onnx": "d337ce1b1cbca907a4063223517af6db7e89f5c9e8d6a2f6a289babc256f4469",  # ONNX export, INT8
}
# Each variant: the repository, the folder inside it, the weights file, and the runtime that reads it
VARIANTS = {
    "english": {"repo": LAYA, "sub": "", "weights": "model.safetensors", "runtime": "torch"},
    "multilingual": {"repo": LAYA, "sub": "multilingual", "weights": "model.safetensors", "runtime": "torch"},
    "typed-decisions": {"repo": LAYA, "sub": "typed-decisions", "weights": "model.safetensors", "runtime": "torch"},
    "english-onnx": {"repo": LAYA_ONNX, "sub": "", "weights": "model.onnx", "runtime": "onnx"},
    "english-onnx-int8": {"repo": LAYA_ONNX, "sub": "", "weights": "model_int8.onnx", "runtime": "onnx"},
}
EN_ORDER = ("english-onnx-int8", "english-onnx", "english", "typed-decisions")  # auto's English choice: the first one on disk
QTYPES = {"choice": 0, "score": 1, "noul": 2}  # question types as the model's type embedding numbers them
TEMP_MIN, TEMP_MAX = 0.5, 5.0  # temperatures outside this range are clamped, as the maker's runtime does
OPTION_CAP = 48  # tokens kept of one option's text, as in training
HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힯]")  # Korean letters: the English checkpoint cannot read them


class LayaUnavailable(RuntimeError):
    """The files or the libraries for a variant are missing. The caller falls back to another backend."""


def setting(name: str, default: str = "") -> str:
    """OFFEROWL_<name>, else the default (an empty value counts as unset)."""
    return os.environ.get("OFFEROWL_" + name, "").strip() or default  # one prefix: these settings are new


def model_dir() -> pathlib.Path:
    """The folder that holds the downloaded repositories."""
    return pathlib.Path(setting("LAYA_DIR", str(pathlib.Path.home() / ".cache" / "offerowl" / "laya"))).expanduser()  # a cache folder by default


def files_of(variant: str) -> list:
    """(repository, path in the repository) of every file a variant needs."""
    v = VARIANTS[variant]  # the variant's description
    sub = (v["sub"] + "/") if v["sub"] else ""  # the folder inside the repository
    if v["runtime"] == "onnx":  # the export keeps its files at the top
        names = ["rl_agent_config.json", "tokenizer.json", "tokenizer_config.json", v["weights"]]
    else:  # the maker's layout: encoder config and tokenizer in their own folders
        names = ["rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json", v["weights"]]
    return [(v["repo"], sub + n) for n in names]  # one entry per file


def local_path(repo: tuple, path: str) -> pathlib.Path:
    """Where one file of a repository sits on this PC: <dir>/<repository name>/<path>."""
    return model_dir() / repo[0].split("/")[1] / path  # laya/... or laya-onnx/...


def present(variant: str) -> bool:
    """Are all files of a variant on this PC?"""
    return all(local_path(r, p).is_file() for r, p in files_of(variant))  # every file, not just the weights


def missing_libs(variant: str) -> list:
    """Python libraries a variant needs that cannot be imported here."""
    import importlib.util  # find_spec looks without importing
    need = ["numpy", "tokenizers"] + (["onnxruntime"] if VARIANTS[variant]["runtime"] == "onnx" else ["torch", "transformers", "safetensors"])
    return [m for m in need if importlib.util.find_spec(m) is None]  # the ones that are absent


def sha256_of(path: pathlib.Path) -> str:
    """sha256 of a file, read in pieces so a 1.7 GB file does not fill memory."""
    h = hashlib.sha256()  # the running hash
    with path.open("rb") as f:  # binary
        for block in iter(lambda: f.read(1 << 20), b""):  # one megabyte at a time
            h.update(block)  # feed it
    return h.hexdigest()  # hex like the Hub shows it


def fetch(variant: str, log=print) -> list:
    """Download every missing file of a variant from the pinned revision and check the large ones. Returns the paths."""
    got = []  # the files on disk afterwards
    for repo, path in files_of(variant):  # each file the variant needs
        dest = local_path(repo, path)  # where it goes
        if dest.is_file():  # already here: nothing to fetch
            got.append(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)  # the repository's folders
        url = f"{HUB}/{repo[0]}/resolve/{repo[1]}/{path}"  # the pinned revision, not main
        log(f"{url} -> {dest}")  # say what is downloaded, since it can be large
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:  # same folder, so the rename is atomic
            with urllib.request.urlopen(url, timeout=60) as r:  # follows the Hub's redirect to its file store
                shutil.copyfileobj(r, tmp, 1 << 20)  # stream to disk
        part = pathlib.Path(tmp.name)  # the finished download under a temporary name
        want = SHA256.get(path)  # the pinned hash, for the large files
        if want and sha256_of(part) != want:  # not the file that was measured
            part.unlink()  # never keep a file that failed its check
            raise LayaUnavailable(f"{path}: sha256 does not match the pinned file")
        part.replace(dest)  # now under its real name
        got.append(dest)
    return got


# ---------------------------------------------------------------- the published input layout

class Tokens:
    """A tokenizer.json with the special tokens its tokenizer_config.json names."""

    def __init__(self, tokenizer_json: pathlib.Path, config_json: pathlib.Path):
        from tokenizers import Tokenizer  # the fast tokenizer library; imported only when Laya is used
        self.tk = Tokenizer.from_file(str(tokenizer_json))  # the vocabulary and the rules
        self.tk.no_truncation()  # the layout below cuts where it must, never the tokenizer
        self.tk.no_padding()  # padding is done per batch
        cfg = json.loads(config_json.read_text(encoding="utf-8"))  # names of the special tokens
        self.mask_token = cfg["mask_token"]  # [MASK] or <mask>: removed from any text before encoding
        self.cls, self.sep, self.mask, self.pad = (self.tk.token_to_id(cfg[k]) for k in ("cls_token", "sep_token", "mask_token", "pad_token"))  # their ids

    def ids(self, text: str) -> list:
        """Token ids of a text, without special tokens (the layout adds its own)."""
        return self.tk.encode(text, add_special_tokens=False).ids  # the same call the published code makes through transformers


def render_options(q: dict) -> list:
    """The text of each option, in option order, as the model was trained to read them."""
    crit = q.get("criteria")  # options and their descriptions
    if q["type"] == "choice":  # "key: description", or the key alone
        crit = {c: None for c in crit} if isinstance(crit, list) else crit  # a list of keys is a dict without descriptions
        return [str(k) if v in (None, "") else f"{k}: {v}" for k, v in crit.items()]
    if q["type"] == "score":  # ordered levels
        return [f"level {i}: {c}" for i, c in enumerate(crit)]
    crit = crit or {}  # noul: always false then true, so the second probability is the answer
    return ["false: " + (crit.get("false") or "no, the statement does not hold"), "true: " + (crit.get("true") or "yes, the statement holds")]


def build_sequence(tok: Tokens, state, q: dict, max_len: int, head_max_len: int) -> tuple:
    """[CLS] <type> question: instructions [SEP] [MASK] option0 [MASK] option1 ... [SEP] state [SEP].
    Returns (ids, marker positions, how many state tokens were cut). The head gets at most head_max_len tokens and
    the state the rest; a long state loses its end."""
    text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)  # a dict state is read as JSON
    ins = str(q["instructions"]).replace(tok.mask_token, " ")  # a mask token inside the text would confuse the markers
    head = tok.ids(f"{q['type']} question: {ins}")  # the question line
    opts = [[tok.mask] + tok.ids(" " + o.replace(tok.mask_token, " "))[:OPTION_CAP] for o in render_options(q)]  # one marker and text per option
    budget = head_max_len - sum(len(o) for o in opts)  # what is left for the question line
    if budget < 16:  # too many or too long options: every option is cut to the same size
        per = max(4, (head_max_len - 16) // max(1, len(opts)))  # tokens per option
        opts = [o[:per] for o in opts]  # each keeps its marker and its first words
        budget = head_max_len - sum(len(o) for o in opts)  # recomputed after the cut
    ids = [tok.cls] + head[:max(8, budget)] + [tok.sep]  # the question line keeps at least eight tokens
    markers = []  # where each option's [MASK] sits
    for o in opts:  # in option order
        markers.append(len(ids))  # its marker position
        ids.extend(o)  # the marker and the option text
    ids.append(tok.sep)  # end of the head
    room = max(0, max_len - len(ids) - 1)  # state tokens that fit, leaving the closing [SEP]
    st = tok.ids(text.replace(tok.mask_token, " "))  # the whole state
    ids = ids + st[:room] + [tok.sep]  # the start of the state is kept
    return ids[:max_len], [m for m in markers if m < max_len], max(0, len(st) - room)  # the cut count lets a caller see truncation


# ---------------------------------------------------------------- the model

def _torch_model(encoder_dir: pathlib.Path, head_layers: int, n_act: int):
    """The decision model in torch: the encoder with its configuration, a type embedding, a two-layer transformer
    head, an option scorer and an act head. Parameter names match the published weights, so they load strictly."""
    import torch  # only the torch variants need it
    from torch import nn  # layers
    from transformers import AutoConfig, AutoModel  # the encoder is a stock ModernBERT

    class DecisionModel(nn.Module):  # the published architecture
        def __init__(self, encoder):
            super().__init__()
            self.encoder = encoder  # ModernBERT-large or mmBERT-base
            d = encoder.config.hidden_size  # width of every layer below
            heads = max(1, d // 64)  # attention heads of the decision head
            layer = nn.TransformerEncoderLayer(d, heads, 4 * d, 0.1, batch_first=True, norm_first=True)  # pre-norm, as trained
            self.head = nn.TransformerEncoder(layer, head_layers, enable_nested_tensor=False)  # two layers over the encoder output
            self.type_emb = nn.Embedding(3, d)  # choice, score or noul
            self.scorer = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))  # one logit per marker
            self.act_head = nn.Sequential(nn.Linear(d + 4, 256), nn.GELU(), nn.Linear(256, n_act))  # act or escalate; its maker says it carries no signal yet
            self.register_buffer("temperature", torch.ones(3))  # stored in the weights, not used: the config's temperatures are

        def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
            h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state  # token states
            h = h + self.type_emb(qtype)[:, None, :]  # every token learns the question type
            pad = ~attention_mask.bool()  # the head ignores padding
            for layer in self.head.layers:  # the two head layers
                h = layer(h, src_key_padding_mask=pad)
            idx = marker_pos.clamp(min=0)[:, :, None].expand(-1, -1, h.size(-1))  # gather index of every marker
            logits = self.scorer(torch.gather(h, 1, idx)).squeeze(-1).float()  # one logit per option
            return logits.masked_fill(~marker_mask, -1e4)  # padded markers never win

    cfg = AutoConfig.from_pretrained(str(encoder_dir))  # the encoder's shape; transformers 5 reads mmBERT's RoPE settings from it
    encoder = AutoModel.from_config(cfg, attn_implementation="sdpa")  # architecture only; the weights come from the checkpoint
    return DecisionModel(encoder)


class Model:
    """One variant, loaded on first use and kept until unload()."""

    def __init__(self, variant: str, threads: int | None = None):
        if variant not in VARIANTS:  # a typo in a setting
            raise LayaUnavailable(f"unknown Laya variant {variant} (choices: {', '.join(VARIANTS)})")
        self.variant, self.spec = variant, VARIANTS[variant]  # which one, and its description
        self.threads = threads or int(setting("LAYA_THREADS", "4"))  # CPU threads
        self.lock = threading.Lock()  # one load at a time
        self.net = None  # the session or the torch module, once loaded
        self.load_sec = 0.0  # how long the load took
        self.rss_after_load_mb = None  # this process's peak memory right after the load

    def folder(self) -> pathlib.Path:
        """The variant's folder on this PC."""
        return local_path(self.spec["repo"], self.spec["sub"])  # an empty sub-folder is the repository's own folder

    def load(self):
        """Load the tokenizer, the config and the weights. Raises LayaUnavailable when something is missing."""
        with self.lock:  # a second caller waits for the first load
            if self.net is not None:  # loaded already
                return self
            libs = missing_libs(self.variant)  # libraries first: a clear message beats an ImportError
            if libs:
                raise LayaUnavailable(f"Laya {self.variant} needs {', '.join(libs)}")
            if not present(self.variant):  # files next
                if setting("LAYA_DOWNLOAD") != "1":  # never download unless asked
                    raise LayaUnavailable(f"Laya {self.variant} is not on this PC ({model_dir()}); run `python3 src/decide/cli.py fetch {self.variant}`")
                fetch(self.variant)  # the one download the setting allows
            t0 = time.time()  # load time
            f = self.folder()  # the variant's files
            self.cfg = json.loads((f / "rl_agent_config.json").read_text(encoding="utf-8"))  # lengths and temperatures
            onnx = self.spec["runtime"] == "onnx"  # the two runtimes keep the tokenizer in different places
            self.tok = Tokens(f / "tokenizer.json", f / "tokenizer_config.json") if onnx else Tokens(f / "tokenizer" / "tokenizer.json", f / "tokenizer" / "tokenizer_config.json")
            if onnx:  # onnxruntime on the CPU
                import onnxruntime as ort  # imported only here
                opt = ort.SessionOptions()  # thread settings
                opt.intra_op_num_threads = self.threads  # within one operator
                opt.inter_op_num_threads = 1  # one operator at a time keeps the thread count honest
                opt.log_severity_level = 3  # no GPU discovery warnings on a CPU-only PC
                self.net = ort.InferenceSession(str(f / self.spec["weights"]), opt, providers=["CPUExecutionProvider"])
            else:  # torch on the CPU
                import torch  # imported only here
                from safetensors.torch import load_file  # the weights file, read without pickle
                torch.set_num_threads(self.threads)  # CPU threads
                net = _torch_model(f / "encoder", self.cfg.get("head_layers", 2), len(self.cfg.get("act_costs", {})) + 1)  # the architecture
                state = load_file(str(f / self.spec["weights"]))  # stored in FP16; loading copies into the FP32 parameters, so no second FP32 copy is made
                try:
                    net.load_state_dict(state, strict=True)  # every name and shape must match the published architecture
                except RuntimeError as e:  # another architecture under the same name
                    raise LayaUnavailable(f"Laya {self.variant}: weights do not fit ({str(e)[:200]})")
                self.net = net.eval()  # inference mode: no dropout
            self.load_sec = time.time() - t0  # reported by the evaluation
            self.rss_after_load_mb = peak_rss_mb()  # the model's memory shows here
        return self

    def unload(self):
        """Free the model."""
        with self.lock:
            self.net = None  # the session or module goes with its last reference

    def temperature(self, qtype: int, k: int) -> float:
        """The fitted temperature for a question type and option count, clamped as the maker's runtime does."""
        size = "2" if k <= 2 else "3-5" if k <= 5 else "6-10" if k <= 10 else "11+"  # the published buckets
        name = {0: "choice", 1: "score", 2: "noul"}[qtype]  # bucket names use the type's name
        t = (self.cfg.get("temperature_by_options") or {}).get(f"{name}:{size}", (self.cfg.get("temperature") or [1.0, 1.0, 1.0])[qtype])  # bucket first, then the type
        return min(TEMP_MAX, max(TEMP_MIN, float(t)))  # a sharpening temperature below 0.5 is refused

    def encode(self, state, q: dict) -> dict:
        """One question about one state as model input."""
        ids, markers, cut = build_sequence(self.tok, state, q, int(self.cfg["max_len"]), int(self.cfg["head_max_len"]))  # the published layout
        if len(markers) != len(render_options(q)):  # an option fell off the end: the answer space would be wrong
            raise LayaUnavailable("the options of this question do not fit the model's head")
        return {"ids": ids, "markers": markers, "qtype": QTYPES[q["type"]], "cut": cut}

    def logits(self, rows: list) -> list:
        """Raw option logits for encoded rows, run as one padded batch."""
        import numpy as np  # arrays for both runtimes
        n, width = len(rows), max(len(r["ids"]) for r in rows)  # batch size and padded length
        if self.spec["runtime"] == "onnx":  # the export traced its head's attention at 512 tokens, so its graph runs at that length only
            width = int(self.cfg["max_len"])  # every row is padded to the full length; padding is masked, so the answer is the same
        k = max(len(r["markers"]) for r in rows)  # most options in the batch
        ids = np.full((n, width), self.tok.pad, dtype=np.int64)  # padding everywhere first
        att = np.zeros((n, width), dtype=np.int64)  # attention mask
        pos = np.zeros((n, k), dtype=np.int64)  # marker positions
        mmask = np.zeros((n, k), dtype=bool)  # which marker slots are real
        for i, r in enumerate(rows):  # fill each row
            ids[i, :len(r["ids"])] = r["ids"]
            att[i, :len(r["ids"])] = 1
            pos[i, :len(r["markers"])] = r["markers"]
            mmask[i, :len(r["markers"])] = True
        qtype = np.array([r["qtype"] for r in rows], dtype=np.int64)  # one type per row
        if self.spec["runtime"] == "onnx":  # the export's input names
            out = self.net.run(["logits"], {"input_ids": ids, "attention_mask": att, "marker_pos": pos, "marker_mask": mmask, "qtype": qtype})[0]
        else:  # torch
            import torch  # loaded already
            with torch.inference_mode():  # no gradients
                out = self.net(torch.from_numpy(ids), torch.from_numpy(att), torch.from_numpy(pos), torch.from_numpy(mmask), torch.from_numpy(qtype)).numpy()
        return [out[i, :len(r["markers"])].astype(float).tolist() for i, r in enumerate(rows)]  # each row's own options

    def ask(self, state, q: dict) -> dict:
        """One question about one state: the chosen option, every option's probability, and the confidence (the top
        probability after the fitted temperature)."""
        return self.ask_many([(state, q)])[0]  # a batch of one

    def ask_many(self, pairs: list, batch: int = 8) -> list:
        """Many (state, question) pairs, in batches. Each answer: {choice, probabilities, confidence, cut}."""
        self.load()  # on first use
        rows = [self.encode(s, q) for s, q in pairs]  # encode everything first, so a bad question fails before any run
        out = []  # answers in order
        for i in range(0, len(rows), batch):  # one forward pass per batch
            for r, z, (s, q) in zip(rows[i:i + batch], self.logits(rows[i:i + batch]), pairs[i:i + batch]):
                t = self.temperature(r["qtype"], len(z))  # calibration for this bucket
                m = max(z)  # stable softmax
                e = [math.exp((x - m) / t) for x in z]  # exponentials
                p = [x / sum(e) for x in e]  # probabilities
                keys = list(q["criteria"]) if q["type"] == "choice" else [str(j) for j in range(len(p))]  # option names
                best = max(range(len(p)), key=p.__getitem__)  # the top option
                out.append({"choice": keys[best], "probabilities": dict(zip(keys, (round(x, 4) for x in p))), "confidence": round(p[best], 4), "cut": r["cut"]})
        return out


def peak_rss_mb() -> float:
    """This process's peak resident memory in MB (Linux reports kilobytes, macOS bytes)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # the high-water mark
    return round(peak / (1024 * 1024) if os.uname().sysname == "Darwin" else peak / 1024, 1)  # to megabytes


def has_hangul(text: str) -> bool:
    """Does the text hold Korean letters?"""
    return bool(HANGUL.search(text or ""))


def english_variant() -> str:
    """The variant auto uses for text without Hangul: the setting, else the first of EN_ORDER on this PC."""
    chosen = setting("LAYA_EN")  # an explicit choice
    if chosen:
        return chosen
    return next((v for v in EN_ORDER if present(v)), EN_ORDER[0])  # the first that is downloaded; else the default, whose load explains what is missing


_LOADED = {}  # variant name to Model, so a process loads each variant once


def model(variant: str) -> Model:
    """The shared Model for a variant."""
    if variant not in _LOADED:  # first request
        _LOADED[variant] = Model(variant)
    return _LOADED[variant]


def route(text: str) -> str:
    """The variant for one input: OFFEROWL_LAYA_MODEL when set, else multilingual for Hangul and the English one otherwise."""
    forced = setting("LAYA_MODEL", "auto")  # the person's choice
    if forced != "auto":
        return forced
    return "multilingual" if has_hangul(text) else english_variant()  # the English checkpoints cannot read Korean


# ---------------------------------------------------------------- the decision backend

def question(task: str) -> dict:
    """A task's question in Laya's shape: a choice over the task's labels, each with its description. A choice with
    described keys, not a yes/no question: the maker's card warns that yes/no answers can follow their labels."""
    from decide import TASKS  # the shared task definitions
    spec = TASKS[task]  # labels, question and descriptions
    return {"type": "choice", "instructions": spec["question"], "criteria": {k: spec["options"][k] for k in spec["labels"]}}


def states(task: str, item: dict) -> list:
    """The states Laya reads for one item. A coverage item gives one state per evidence text, since a state has room
    for about 320 tokens on the English checkpoint; the others give one."""
    if task == "line_kind":  # the line alone
        return [item["text"]]
    if task == "coverage":  # the line with each candidate in turn
        ev = item["evidence"] if isinstance(item["evidence"], list) else [item["evidence"]]  # one text or a list
        return [{"posting line": item["line"], "evidence": str(e)} for e in ev] or [{"posting line": item["line"], "evidence": ""}]  # no evidence still gets a state
    if task == "claim":  # the sentence and its evidence
        ev = item["evidence"] if isinstance(item["evidence"], str) else " ".join(map(str, item["evidence"]))  # blocks are joined
        return [{"claim": item["claim"], "evidence": ev}]
    return [{"statement A": item["a"], "statement B": item["b"]}]  # contradiction: the two statements


def whole_state(task: str, item: dict):
    """The one state a reader of long states gets for an item (Jev, Vega): Laya's state for it, with a coverage item's
    evidence texts together, so one call sees every candidate. Only the task's fields are in it, never an item's id."""
    if task == "coverage":  # the line with all its candidates at once
        ev = item["evidence"] if isinstance(item["evidence"], list) else [item["evidence"]]  # one text or a list
        return {"posting line": item["line"], "evidence": [str(e) for e in ev]}
    return states(task, item)[0]  # a posting line as plain text; a claim or a pair as an object


def decide(task: str, items: list, variant: str | None = None, **_) -> list:
    """Laya's decision for each item. A coverage item takes the candidate with the highest expected strength
    (strong 2, weak 1, none 0), so one candidate that shows the line is enough, as for the rules and the agent."""
    from decide import DecideUnavailable, result  # the shared shape
    q = question(task)  # the same question for every item
    out = []  # decisions in order
    for it in items:  # one item at a time: the time per decision is what the panel sees
        text = json.dumps(it, ensure_ascii=False)  # every field, for the language test
        name = variant or route(text)  # Hangul goes to the multilingual checkpoint
        t0 = time.time()  # the decision's own time, including its candidates
        try:
            answers = model(name).ask_many([(s, q) for s in states(task, it)], batch=16)  # all of the item's states in one batch
        except LayaUnavailable as e:  # missing files or libraries
            raise DecideUnavailable(str(e))
        if task == "coverage":  # the best candidate decides
            weight = {"strong": 2.0, "weak": 1.0, "none": 0.0}  # expected strength
            best = max(range(len(answers)), key=lambda i: sum(weight[k] * p for k, p in answers[i]["probabilities"].items()))  # the strongest candidate
            a = answers[best]  # its answer stands for the item
        else:  # one state, one answer
            best, a = 0, answers[0]
        out.append(result(task, a["choice"], a["probabilities"], f"laya:{name}", (time.time() - t0) * 1000, best=best, cut=a["cut"]))
    return out


def status() -> dict:
    """Which variants are on this PC and whether their libraries import: ready when the variants auto needs are there."""
    have = {v: present(v) and not missing_libs(v) for v in VARIANTS}  # usable variants
    forced = setting("LAYA_MODEL", "auto")  # a fixed choice
    need = [forced] if forced != "auto" else [english_variant(), "multilingual"]  # what a decision may load
    ready = all(have.get(v) for v in need)  # every one of them
    why = "" if ready else f"missing: {', '.join(v for v in need if not have.get(v))} in {model_dir()}"  # what to fetch
    return {"ready": ready, "why": why, "variants": have}
