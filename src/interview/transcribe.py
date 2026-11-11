"""The optional speech-to-text step of practice mode: a recorded answer in, its words and their times out.

It uses faster-whisper when it is installed, and nothing otherwise: the page
then asks for a typed answer and still measures pauses from the microphone level. The model never runs inside the
server process. Each recording is decoded by a separate process (this file run as a script), because a process that
holds the model's native thread pool must not start other programs, and the server starts the agent's CLI. The worker
also lowers its own priority, so a transcription never makes the rest of the PC wait.

Settings:
  OFFEROWL_STT_PYTHON     the Python that has faster-whisper (default: this one)
  OFFEROWL_WHISPER_MODEL  model size or folder (default: base; small is slower and more accurate)
  OFFEROWL_WHISPER_THREADS  CPU threads for the decode (default: 4)
  OFFEROWL_WHISPER_DOWNLOAD=1  allow downloading the model once; without it only a model already on this PC is used

    python3 src/interview/transcribe.py <audio file> [--model base] [--lang en]   prints one JSON object
"""
import json  # the worker's answer
import os  # settings
import pathlib  # paths
import subprocess  # the worker process
import sys  # the interpreter
import tempfile  # the recording on disk for the worker

HERE = pathlib.Path(__file__).resolve()  # this file, which is also the worker
MAX_BYTES = 30 * 1024 * 1024  # the largest recording accepted (about half an hour of Opus)
TIMEOUT = 300  # seconds a transcription may take before it is given up
# Whisper leaves out "um" and "uh" unless the text before the audio has them; this prompt keeps the fillers in
FILLER_PROMPT = "Um, uh, so, like, you know, I mean, well, I'll answer the question now."
_state = {"ok": None, "why": ""}  # the availability check, done once per server


def python():  # the interpreter that runs the worker
    """The Python that runs the worker: OFFEROWL_STT_PYTHON, else this one."""
    return os.environ.get("OFFEROWL_STT_PYTHON") or sys.executable  # a venv with faster-whisper can be named


def available():
    """(installed, a short reason). Checked once by asking the worker's Python to import faster-whisper."""
    if _state["ok"] is None:  # first call
        try:
            r = subprocess.run([python(), "-c", "import faster_whisper"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)  # import only, no model
            _state["ok"] = r.returncode == 0  # installed or not
            _state["why"] = "faster-whisper" if _state["ok"] else "faster-whisper is not installed"  # what the page shows
        except (OSError, subprocess.TimeoutExpired) as e:  # the named Python is missing or hangs
            _state["ok"], _state["why"] = False, f"cannot run {python()}: {e}"  # the reason for the page
    return _state["ok"], _state["why"]


def suffix(mime):  # the worker reads the file by its contents, but a fitting name helps the decoder
    """A file suffix for a recording's MIME type."""
    m = (mime or "").lower()  # such as audio/webm;codecs=opus
    return ".ogg" if "ogg" in m else ".mp4" if ("mp4" in m or "aac" in m or "m4a" in m) else ".wav" if "wav" in m else ".webm"


def transcribe(audio, mime="", lang="en"):
    """{text, words: [{w, start, end}], seconds, language} of a recording, or {error} when it cannot be transcribed."""
    ok, why = available()  # installed?
    if not ok:  # no speech model on this PC: the page asks for a typed answer
        return {"error": why, "code": "no_stt"}
    if not audio or len(audio) > MAX_BYTES:  # an empty or oversized body
        return {"error": "the recording is empty or too large", "code": "bad_audio"}
    with tempfile.TemporaryDirectory(prefix="offerowl-stt-") as tmp:  # removed afterwards, with the recording
        path = pathlib.Path(tmp) / ("answer" + suffix(mime))  # the recording on disk
        path.write_bytes(audio)  # as the browser sent it
        cmd = [python(), str(HERE), str(path), "--lang", lang]  # the worker
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)  # one decode per process
        except subprocess.TimeoutExpired:  # a stuck decode is given up
            return {"error": f"transcription took longer than {TIMEOUT} s", "code": "timeout"}
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}  # the worker prints one JSON line last
    except ValueError:  # it printed something else
        out = {}
    if r.returncode != 0 or not isinstance(out, dict) or "text" not in out:  # the worker failed
        return {"error": (out.get("error") if isinstance(out, dict) else "") or r.stderr.strip()[-300:] or "transcription failed", "code": "failed"}
    return out


def work(path, model_name, lang):
    """The worker: decode one file with faster-whisper and return the result as a dict."""
    try:
        os.nice(10)  # below the interactive work on this PC
    except (OSError, AttributeError):  # not allowed or not on this system
        pass
    from faster_whisper import WhisperModel  # the heavy import happens only here
    threads = int(os.environ.get("OFFEROWL_WHISPER_THREADS", "4") or 4)  # a few cores, not all of them
    local = os.environ.get("OFFEROWL_WHISPER_DOWNLOAD", "") != "1"  # no download unless asked once
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(1, threads), num_workers=1,
                         local_files_only=local)  # int8 on the CPU, small and quick enough for speech
    segments, info = model.transcribe(path, language=lang or None, word_timestamps=True, vad_filter=False,
                                      initial_prompt=FILLER_PROMPT, condition_on_previous_text=False)  # word times give the pauses
    words, parts = [], []  # every word with its times; the text of each segment
    for seg in segments:  # decoding happens while the segments are read
        parts.append(seg.text.strip())  # the segment's text
        for w in seg.words or []:  # its words
            words.append({"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)})  # times in seconds
    return {"text": " ".join(p for p in parts if p).strip(), "words": words, "seconds": round(float(info.duration), 2),
            "language": info.language}


def main(argv=None):  # the worker's entry point
    """Run as a script: transcribe one file and print one JSON line."""
    import argparse  # the worker's options
    ap = argparse.ArgumentParser(description="transcribe one recorded answer (practice mode)")  # the worker's command line
    ap.add_argument("path")  # the recording
    ap.add_argument("--model", default=os.environ.get("OFFEROWL_WHISPER_MODEL", "base"))  # model size or folder
    ap.add_argument("--lang", default="en")  # the interview's language
    a = ap.parse_args(argv)  # parse
    try:
        out = work(a.path, a.model, a.lang)  # the decode
    except Exception as e:  # noqa: BLE001  a missing model or a decode error: say it as JSON
        print(json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}))  # one line, read by transcribe()
        return 1
    print(json.dumps(out, ensure_ascii=False))  # one line, read by transcribe()
    return 0


if __name__ == "__main__":  # the worker
    sys.exit(main())
