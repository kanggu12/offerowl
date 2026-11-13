"""The optional similarity half of the search (off unless `serve --model DIR` or OFFEROWL_SEARCH_MODEL names a model).

The page ranks by keywords (BM25) by itself, and that is the default. With a model, this module embeds every view
of every item with a multilingual model (bge-m3, int8 ONNX on CPU), caches the vectors on disk, and for each query
returns every item's best cosine similarity and which view matched. The model loads only while the page's switch is
on, so a server can stay up and still be small while idle. numpy, onnxruntime and tokenizers are imported only here,
and only when the model is switched on, so the keyword path needs nothing outside the standard library.
"""
import ctypes  # hand memory freed by the model back to the system
import functools  # small cache for repeated queries
import gc  # collect the model's objects at once when it is switched off
import hashlib  # cache keys for embedded texts
import os  # OFFEROWL_SEARCH_MODEL
import pathlib  # paths
import threading  # the model loads in the background; locks around switching and rebuilding

MAX_TOKENS = 512  # long chunks are cut here; views are short anyway
MODEL_TAG = "bge-m3-int8"  # part of every cache key, so a model change never reuses old vectors
SETTING = "OFFEROWL_SEARCH_MODEL"  # the model's folder, named once for `serve` and for the panel's kit view
FILES = ("tokenizer.json", "onnx/model_int8.onnx")  # what that folder holds


def from_setting():
    """(folder, problem) of OFFEROWL_SEARCH_MODEL: the folder and "" when it holds the model's files; (None, "") when
    the setting is empty; (None, the files not found there) otherwise, so the caller can say why there is no switch."""
    raw = os.environ.get(SETTING, "").strip()  # an empty setting is no setting
    if not raw:
        return None, ""
    folder = pathlib.Path(raw).expanduser()  # ~ as a person writes it
    missing = [f for f in FILES if not (folder / f).is_file()]  # both are needed before the switch can load anything
    return (None, ", ".join(missing)) if missing else (folder, "")


def rss_mb():
    """This process's resident memory in MB, for the page's status tooltip."""
    try:
        for line in pathlib.Path("/proc/self/status").read_text(encoding="utf-8").splitlines():  # Linux exposes it here
            if line.startswith("VmRSS:"):  # "VmRSS:   123456 kB"
                return int(line.split()[1]) // 1024  # kB to MB
    except OSError:  # not on Linux: no number
        pass
    return None  # no reading: the tooltip leaves the number out


def key(text):
    """Cache key for one embedded text."""
    return hashlib.sha1(f"{MODEL_TAG}\n{text}".encode("utf-8")).hexdigest()  # the model tag is hashed in, so another model gets other keys


class Dense:
    """The embedding model and the view vectors, present only while semantic search is switched on."""

    def __init__(self, model_dir, cache_dir, threads=6, embedder=None):  # model_dir may be None when a stand-in embedder is given
        self.model_dir = pathlib.Path(model_dir) if model_dir else None  # tokenizer.json and onnx/model_int8.onnx
        self.cache = pathlib.Path(cache_dir)  # embedded vectors survive restarts here
        self.threads = threads  # CPU threads for the model
        self.embedder = embedder  # a stand-in embed function for tests; None means the real model
        self.lock = threading.Lock()  # one switch at a time
        self.build_lock = threading.Lock()  # one vector build at a time (the warm-up and a query may both start one)
        self.state = "off"  # off, loading or on
        self.error = ""  # why the last load failed, shown on the page
        self.sess = self.tok = None  # the ONNX session and tokenizer while on
        self.inputs, self.out = set(), None  # input names the export wants, its output name
        self.mat = None  # [views, dim] matrix while on
        self.owner = self.labels = self.texts = self.weights = None  # one entry per view
        self.built_for = None  # the item stamp the vectors belong to
        self.embed_query = functools.lru_cache(maxsize=512)(self._embed_one)  # typing repeats prefixes and the same questions

    # ----- the model -----

    def _load(self):
        """Create the session (or take the stand-in). Runs in a worker thread."""
        try:
            if self.embedder is None:  # the real model
                import onnxruntime as ort  # imported on the first switch-on only
                from tokenizers import Tokenizer  # likewise
                tk = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))  # before the session, so a missing file fails fast
                tk.enable_truncation(MAX_TOKENS)  # cap sequence length
                tk.enable_padding(pad_id=tk.token_to_id("<pad>"), pad_token="<pad>")  # XLM-R pads with <pad>
                opts = ort.SessionOptions()  # fixed thread counts keep it inside its CPU share
                opts.intra_op_num_threads = self.threads  # threads inside one operator
                opts.inter_op_num_threads = 1  # operators run one after another
                # the int8 export, CPU only, with the thread limits above
                sess = ort.InferenceSession(str(self.model_dir / "onnx" / "model_int8.onnx"), opts, providers=["CPUExecutionProvider"])
                with self.lock:  # publish the session and the new state together
                    self.tok, self.sess = tk, sess  # both are published at once
                    self.inputs = {i.name for i in sess.get_inputs()}  # some exports also want token_type_ids
                    self.out = sess.get_outputs()[0].name  # the hidden states
            with self.lock:  # both paths end here; the state changes only under the lock
                self.state, self.error = "on", ""  # ready
        except Exception as e:  # a broken model file must not take the server down
            with self.lock:  # the failure is published under the lock too
                self.sess, self.tok, self.state, self.error = None, None, "off", str(e)[:200]  # back to off, with the reason

    def switch(self, on):
        """Turn semantic search on (load in the background) or off (drop the model and its vectors)."""
        with self.lock:  # one switch at a time
            if on and self.state == "off":  # start loading; the page polls the state
                self.state = "loading"  # so a second switch-on does not start another load
                threading.Thread(target=self._load, daemon=True).start()  # load off the request thread, so the page answers at once
            elif not on and self.state == "on":  # a switch-off during loading waits for the load to finish
                self.sess, self.tok, self.inputs, self.out, self.state = None, None, set(), None, "off"  # queries now get 503
                self.mat, self.built_for = None, None  # the matrix is the other large piece of memory
                self.embed_query.cache_clear()  # cached query vectors belong to the old session
                gc.collect()  # free the session's objects now
                try:
                    ctypes.CDLL("libc.so.6").malloc_trim(0)  # and give the freed pages back to the system
                except OSError:  # another C library: the memory is freed, just not returned yet
                    pass
            return self.state  # the page shows the state after the switch

    def embed(self, texts, batch=16):
        """L2-normalised CLS vectors for a list of texts (bge-m3 dense embedding)."""
        import numpy as np  # only with the model
        if self.embedder is not None:  # the stand-in
            vecs = [np.asarray(self.embedder(t), dtype=np.float32) for t in texts]  # one vector per text from the stand-in
            return [v / max(1e-9, float(np.linalg.norm(v))) for v in vecs]  # unit length like the real path; the floor avoids a division by zero
        sess, tk, inputs, out_name = self.sess, self.tok, self.inputs, self.out  # hold them for this call; a switch-off may follow
        if sess is None or tk is None:  # semantic search is off
            raise RuntimeError("model off")  # callers treat this as no vectors this time
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # similar lengths share a batch
        out = [None] * len(texts)  # vectors in the caller's order
        for s in range(0, len(order), batch):  # one model call per batch
            idx = order[s:s + batch]  # positions in this batch
            enc = tk.encode_batch([texts[i] for i in idx])  # token ids with padding
            ids = np.array([e.ids for e in enc], dtype=np.int64)  # [B, T]
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)  # 1 for real tokens
            feed = {"input_ids": ids, "attention_mask": mask}  # what every export needs
            if "token_type_ids" in inputs:  # only when the export asks for it
                feed["token_type_ids"] = np.zeros_like(ids)  # a single segment: all zeros
            hidden = sess.run([out_name], feed)[0]  # [B, T, 1024]
            vec = hidden[:, 0, :]  # bge-m3 dense uses the CLS token
            vec = vec / np.linalg.norm(vec, axis=1, keepdims=True)  # unit length, so dot = cosine
            for k, i in enumerate(idx):  # put each vector back in place
                out[i] = vec[k].astype(np.float32)  # float32 keeps the cache and the matrix small
        return out

    def _embed_one(self, q):
        """Embed one query (cached by embed_query)."""
        return self.embed([q])[0]  # a batch of one

    # ----- the vectors -----

    def ensure(self, items, alts, stamp, views):
        """Embed every view of the items (reusing cached vectors) when the model is on and the items changed."""
        if self.state != "on" or self.built_for == stamp:  # nothing to do
            return
        with self.build_lock:  # the second caller waits, then finds the vectors built
            if self.state == "on" and self.built_for != stamp:  # check again: the first caller may have built it, or the model went off
                self._build(items, alts, stamp, views)  # build while holding the lock

    def _build(self, items, alts, stamp, views):
        """Embed the views of the items, from the disk cache where possible."""
        import numpy as np  # only with the model
        owner, labels, texts, weights = [], [], [], []  # one entry per view
        for n, it in enumerate(items):  # flatten the views of every item
            for label, w, text in views(it, alts):  # the corpus decides the views and their weights
                owner.append(n)  # which item this view belongs to
                labels.append(label)  # named in the answer as the matched view
                texts.append(text)  # the text to embed
                weights.append(w)  # how much this kind of view counts
        self.cache.mkdir(parents=True, exist_ok=True)  # the cache folder may be new
        store = self.cache / "vectors.npz"  # every vector ever embedded, by key
        cached = {}  # key -> vector
        if store.is_file():  # load what earlier builds embedded
            with np.load(store) as z:  # the file is closed after reading
                cached = dict(zip(z["keys"].tolist(), z["vecs"]))  # cache key to vector, as saved
        keys = [key(t) for t in texts]  # cache key per view
        todo = sorted({k: t for k, t in zip(keys, texts) if k not in cached}.items())  # texts not embedded yet
        if todo:  # embed only the new texts
            try:
                vecs = self.embed([t for _, t in todo])  # one run for all the new texts
            except RuntimeError:  # switched off in the middle: no vectors this time
                return
            for (k, _), v in zip(todo, vecs):  # add the new vectors to the cache
                cached[k] = v
            used = set(keys)  # keys some view still uses
            keep = [k for k in cached if k in used]  # drop vectors no view uses any more, so the file stays small
            tmp = self.cache / "vectors.tmp.npz"  # write then rename, so a crash never leaves half a file
            np.savez(tmp, keys=np.array(keep), vecs=np.stack([cached[k] for k in keep]))  # keys and vectors in the same order
            tmp.replace(store)  # the rename swaps the file in one step
        with self.lock:  # publish together, so a query sees either the old or the new vectors
            self.mat = np.stack([cached[k] for k in keys]) if keys else None  # [V, dim]
            self.owner = np.array(owner, dtype=np.int64)  # item number per view
            self.labels, self.texts = labels, texts  # for the matched view in each answer
            self.weights = np.array(weights, dtype=np.float32)  # per-view weight, multiplied into the score
            self.built_for = stamp  # these vectors belong to these items

    def scores(self, q, items):
        """[[id, score, view label, view text]] for every item: its best weighted cosine similarity to the query."""
        import numpy as np  # only with the model
        mat, owner, weights, labels, texts = self.mat, self.owner, self.weights, self.labels, self.texts  # one consistent view
        if mat is None:  # vectors not built yet
            raise RuntimeError("vectors not ready")
        qv = self.embed_query(q)  # the query's vector
        sims = (mat @ qv) * weights  # weighted cosine per view
        order = np.lexsort((sims, owner))  # grouped by item, ascending score inside each group
        grp = owner[order]  # item number of each sorted view
        last = np.r_[np.nonzero(np.diff(grp))[0], len(grp) - 1] if len(grp) else np.zeros(0, np.int64)  # best view per group
        best = np.full(len(items), -1.0, dtype=np.float32)  # best score per item (-1 if it has no views)
        which = np.zeros(len(items), dtype=np.int64)  # view index of that best score
        best[grp[last]] = sims[order[last]]  # one write per item
        which[grp[last]] = order[last]  # and which view gave it
        # scores rounded and view text cut, to keep the answer small
        return [[it["id"], round(float(best[n]), 4), labels[which[n]], texts[which[n]][:120]] for n, it in enumerate(items)]
