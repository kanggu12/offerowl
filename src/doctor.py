#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""offerowl doctor: checks what Offerowl needs on this PC and says, for each thing that is missing, what to do.

    offerowl doctor                  every check, in plain words (OFFEROWL_LANG=ko for Korean)
    offerowl doctor --json           the same as JSON, for scripts
    offerowl doctor --only a,b       only these checks (names are listed by --help)
    python3 src/doctor.py            the same from a checkout

Each check ends in one of three states:
  ok    nothing to do
  warn  one feature is missing or may not work; Offerowl still runs
  fail  documents cannot be made until it is fixed
Exit code 0 means no fail; 1 means at least one fail; 2 means a wrong command line. A check never changes anything on
the PC (it creates no folder and installs nothing), never prints a key or an e-mail address, and never calls a model.

The checks are the ones docs/INSTALL.md promises: Python, the data folder, the engine's own folders and libraries, the
typesetting tools (Docker, or the tools inside the container), browsers, the AI backends and their sign-in, fonts, ports
and the PDF reader the interview kit uses.
"""
from __future__ import annotations  # hints stay strings, so new hint syntax runs on older Pythons

import argparse  # the command line
import hashlib  # the render image's tag is the md5 of the Dockerfile
import json  # --json, and the panel's settings file
import os  # environment and write tests
import platform  # the machine and system names
import re  # the Codex sign-in text, the version of Docker
import shutil  # which program is on PATH, free disk
import socket  # is a port taken
import subprocess  # docker, claude, codex
import sys  # the Python that runs this, the module path
import tempfile  # a probe file to prove a folder is writable
import unicodedata  # the display width of Korean letters, so the report's columns line up
import urllib.error  # a server that answers with an error is still a server
import urllib.parse  # hide the password of a server address
import urllib.request  # ask a server whether it is up
import webbrowser  # is there a default browser to open the panel with
import functools  # one call of the browser renderer's own report per run
from dataclasses import asdict, dataclass  # one result per check
from pathlib import Path  # paths

ROOT = Path(__file__).resolve().parent.parent  # the engine's folder: a checkout, the app image's /work, or the package's tree
sys.path.insert(0, str(ROOT / "src"))  # the engine's flat modules: llm gives the messages their language and the AI backends
import llm  # noqa: E402  settings, messages and the backend list (needs the line above)

PANEL_PORT = 8797  # the panel (docs/APP.md); OFFEROWL_PANEL_PORT changes it
MIN_PYTHON = (3, 10)  # the oldest Python the code supports (CI tests it)
MIN_FREE_GB = 1.0  # below this the data folder is nearly full: a build writes some hundred MB
FONT_FILES = ("Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf")  # fonts/ holds these; the panel serves them
BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "microsoft-edge",
            "microsoft-edge-stable", "msedge", "brave-browser")  # Chromium-based browsers, as they are named on PATH
CONTAINER_TOOLS = ("node", "soffice", "chromium", "pdftotext", "tesseract")  # what the render container must hold
STATUS_ORDER = {"ok": 0, "warn": 1, "fail": 2}  # for the summary

# What this program says, in both languages. Placeholders are {names}; tests/packaging checks that the keys and the
# placeholders match. Fix lines are one line each and name the command or the page to use.
MSG = {
    "en": {
        "head": "offerowl doctor: {version}, Python {python}, {system}",
        "in_container": "running inside the Offerowl container",
        "t_python": "Python",
        "t_data": "Data folder",
        "t_engine": "Engine folders",
        "t_libs": "Typesetting libraries",
        "t_render": "Typesetting",
        "t_browser": "Browsers",
        "t_ai": "AI backend",
        "t_fonts": "Fonts",
        "t_ports": "Ports",
        "t_poppler": "PDF reader",
        "mark_ok": "OK  ",
        "mark_warn": "WARN",
        "mark_fail": "FAIL",
        "fix": "Fix: {text}",
        # python
        "python_ok": "Python {version} ({path})",
        "python_old": "Python {version} is older than {need}",
        "python_fix": "Install Python {need} or newer from https://www.python.org/downloads/ and start Offerowl with it.",
        # data folder
        "data_ok": "{path} is writable, {free} GB free",
        "data_low": "{path} is writable but only {free} GB is free",
        "data_low_fix": "Free some disk space, or point OFFEROWL_DATA_DIR at a folder on a bigger disk.",
        "data_bad": "{path} cannot be written by this user",
        "data_bad_fix": "Make the folder writable for your user, or point OFFEROWL_DATA_DIR at a folder you own.",
        # engine folders and libraries
        "engine_ok": "{path} (output folder writable)",
        "engine_bad": "{path} cannot be written, and the engine writes its output there",
        "engine_bad_fix": "Install Offerowl somewhere you own: a virtual environment (pip install . in a checkout), or the checkout itself.",
        "libs_ok": "the libraries of the resume and deck writers are installed",
        "libs_missing": "the libraries of the resume and deck writers are not installed in {path}",
        "libs_missing_fix": "Install them once (needs the network): {command}",
        "libs_missing_fix_html": "Install them once (needs the network and Node.js): cd {path} && npm ci",
        "libs_image_fix": "The app image is incomplete: build it again from deploy/docker/Dockerfile.",
        # typesetting
        "render_container": "inside the container: {tools} found",
        "render_container_missing": "inside the container, but {tools} not found",
        "render_container_fix": "The app image is incomplete: build it again from deploy/docker/Dockerfile.",
        "render_ok": "Docker {version} answers",
        "render_ok_image": "Docker {version} answers, the render image is built",
        "render_ok_noimage": "Docker {version} answers; the render image is built on the first build (several minutes)",
        "render_nodocker": "Docker was not found, and documents are typeset in a Docker container",
        "render_nodocker_fix_linux": "Install Docker Engine (https://docs.docker.com/engine/install/), then add your user to the docker group: sudo usermod -aG docker $USER",
        "render_nodocker_fix_mac": "Install Docker Desktop (https://docs.docker.com/desktop/setup/install/mac-install/) and start it.",
        "render_nodocker_fix_win": "Install Docker Desktop (https://docs.docker.com/desktop/setup/install/windows-install/) with WSL 2, and run Offerowl inside WSL.",
        "render_down": "Docker is installed but its engine does not answer",
        "render_down_fix_linux": "Start it: sudo systemctl start docker (if it says permission denied: sudo usermod -aG docker $USER, then log in again).",
        "render_down_fix_other": "Start Docker Desktop and wait until it says it is running.",
        "render_nobash": "bash was not found, and render/run.sh (which starts the container) is a bash script",
        "render_nobash_fix": "On Windows run Offerowl inside WSL; elsewhere install bash.",
        "render_container_windows": "OFFEROWL_RENDERER=container, but on Windows the container cannot start: render/run.sh is a shell script",
        "render_container_windows_fix": "Leave OFFEROWL_RENDERER unset or set it to html to typeset with Chrome or Edge, or run Offerowl inside WSL.",
        "render_bad_choice": "OFFEROWL_RENDERER is {value}, which is not a renderer",
        "render_bad_choice_fix": "Set OFFEROWL_RENDERER to container (Docker) or html (this PC's Chrome or Edge), or unset it to use Docker where it is here and the browser where it is not.",
        "render_html_ok": "the browser renderer is ready: {browser} ({kind}), Node.js {node}",
        "render_html_missing": "OFFEROWL_RENDERER=html is set, and this PC lacks: {what}",
        "render_html_unknown": "OFFEROWL_RENDERER=html is set, but this copy of Offerowl has no browser renderer to ask",
        "render_html_unknown_fix": "Unset OFFEROWL_RENDERER to typeset in Docker, or install a version with the browser renderer.",
        "render_try_html": "Or typeset with this PC's {kind} and no Docker: set OFFEROWL_RENDERER=html.",
        "need_browser": "a browser",
        "need_node": "Node.js",
        "need_pillow": "Pillow",
        "need_fonts": "the fonts {names}",
        "html_fix_browser": "Install Microsoft Edge or Google Chrome (or point OFFEROWL_BROWSER at a Chromium-based browser).",
        "html_fix_node": "Install Node.js 22 or newer from https://nodejs.org/.",
        "html_fix_pillow": "Install Pillow: python3 -m pip install pillow",
        "html_fix_fonts": "Reinstall Offerowl; the fonts {names} are part of it.",
        # browsers
        "browser_found": "{names}",
        "browser_playwright": "Playwright for Python is installed",
        "browser_none": "no Chromium-based browser and no Playwright found",
        "browser_none_fix": "Install Chromium, Google Chrome or Microsoft Edge. The interview page checks also need: python3 -m pip install playwright && python3 -m playwright install chromium",
        "browser_default": "default browser for the panel: {name}",
        "browser_nodefault": "no default browser to open the panel with",
        "browser_nodefault_fix": "Open http://127.0.0.1:{port} in a browser by hand.",
        # AI
        "ai_in_use": "in use: {name} ({why})",
        "ai_claude_in": "Claude Code is signed in",
        "ai_claude_out": "Claude Code is installed but signed out",
        "ai_claude_unknown": "Claude Code is installed (its sign-in could not be read)",
        "ai_codex_in": "Codex is signed in",
        "ai_codex_out": "Codex is installed but signed out",
        "ai_codex_unknown": "Codex is installed (run its login status to see whether it is signed in)",
        "ai_url_up": "the local model server {url} answers",
        "ai_url_down": "the local model server {url} does not answer",
        "ai_none_set": "no AI backend is set up; the AI steps stop and you fill in the facts yourself",
        "ai_url_unused": "a local model server is named, but OFFEROWL_LLM is not set, so the command line does not use it",
        "ai_fix_unused": "Set OFFEROWL_LLM=openai-compat (the panel's settings menu does this for the panel).",
        "ai_no_url": "OFFEROWL_LLM_URL is not set",
        "ai_chosen_off": "the backend is none; the AI steps stop and you fill in the facts yourself",
        "ai_chosen_unusable": "the chosen backend {name} cannot be used: {why}",
        "ai_fix": "Sign in to Claude Code (claude auth login), or to Codex (codex login), or start a local model server and set OFFEROWL_LLM=openai-compat OFFEROWL_LLM_URL=http://127.0.0.1:11434 OFFEROWL_LLM_MODEL=<model>.",
        "ai_fix_claude": "Sign in: claude auth login",
        "ai_fix_codex": "Sign in: codex login",
        "ai_fix_url": "Start the model server, or correct OFFEROWL_LLM_URL (or the address in the panel's settings).",
        "ai_why_panel": "the panel's setting",
        "ai_why_env": "set by {var}",
        "ai_why_default": "default order",
        "ai_why_argument": "argument",
        "ai_why_none": "nothing is installed",
        # fonts
        "fonts_ok": "Pretendard is in {path}",
        "fonts_missing": "missing in {path}: {names}",
        "fonts_fix": "Reinstall Offerowl; the fonts are part of it.",
        # ports
        "port_free": "{port} is free",
        "port_mine": "{port} is used by a running Offerowl",
        "port_busy": "{port} is used by another program",
        "port_busy_fix": "Stop the program that uses port {port}, or start the panel on another port: offerowl panel --port <number>.",
        # poppler
        "poppler_ok": "{reader} reads PDFs here",
        "poppler_missing": "nothing here reads PDFs: your old PDFs, the page previews and the checks need poppler or pypdfium2",
        "poppler_fix_linux": "Install poppler (sudo apt install poppler-utils), or pypdfium2 (pip install pypdfium2 pillow where Offerowl is installed)",
        "poppler_fix_mac": "Install poppler (brew install poppler), or pypdfium2 (pip install pypdfium2 pillow where Offerowl is installed)",
        "poppler_fix_win": "Install pypdfium2: pip install pypdfium2 pillow where Offerowl is installed. The desktop app already has it.",
        # summary
        "sum_ready": "Result: {warns} warning(s), no problem. Offerowl can make documents.",
        "sum_notready": "Result: {fails} problem(s), {warns} warning(s). The panel starts, but documents cannot be made until the FAIL lines are fixed.",
        "bad_only": "unknown check name(s): {names}. Choices: {choices}",
        "usage_only": "run only these checks, separated by commas ({choices})",
        "usage_json": "print the result as JSON",
        "usage_desc": "Check what Offerowl needs on this PC and say what to do about what is missing.",
    },
    "ko": {
        "head": "offerowl doctor: {version}, Python {python}, {system}",
        "in_container": "Offerowl 컨테이너 안에서 실행 중",
        "t_python": "Python",
        "t_data": "데이터 폴더",
        "t_engine": "엔진 폴더",
        "t_libs": "조판 라이브러리",
        "t_render": "조판",
        "t_browser": "브라우저",
        "t_ai": "AI 백엔드",
        "t_fonts": "글꼴",
        "t_ports": "포트",
        "t_poppler": "PDF 읽기",
        "mark_ok": "정상",
        "mark_warn": "주의",
        "mark_fail": "실패",
        "fix": "해결: {text}",
        "python_ok": "Python {version} ({path})",
        "python_old": "Python {version}이(가) {need}보다 낮다",
        "python_fix": "https://www.python.org/downloads/ 에서 Python {need} 이상을 설치하고, 그것으로 Offerowl을 시작한다.",
        "data_ok": "{path}에 쓸 수 있다. 빈 공간 {free} GB",
        "data_low": "{path}에 쓸 수 있지만 빈 공간이 {free} GB뿐이다",
        "data_low_fix": "디스크 공간을 비우거나, OFFEROWL_DATA_DIR을 더 큰 디스크의 폴더로 정한다.",
        "data_bad": "{path}에 이 사용자가 쓸 수 없다",
        "data_bad_fix": "폴더에 내 사용자의 쓰기 권한을 주거나, OFFEROWL_DATA_DIR을 내가 쓸 수 있는 폴더로 정한다.",
        "engine_ok": "{path} (output 폴더에 쓸 수 있다)",
        "engine_bad": "{path}에 쓸 수 없다. 엔진은 결과물을 여기에 쓴다",
        "engine_bad_fix": "내가 쓸 수 있는 곳에 설치한다: 가상 환경(저장소 복사본에서 pip install .), 또는 저장소 복사본 그대로.",
        "libs_ok": "이력서와 덱 작성 라이브러리가 설치되어 있다",
        "libs_missing": "이력서와 덱 작성 라이브러리가 {path}에 설치되어 있지 않다",
        "libs_missing_fix": "한 번 설치한다(네트워크가 필요하다): {command}",
        "libs_missing_fix_html": "한 번 설치한다(네트워크와 Node.js가 필요하다): cd {path} && npm ci",
        "libs_image_fix": "앱 이미지가 덜 만들어졌다. deploy/docker/Dockerfile로 다시 만든다.",
        "render_container": "컨테이너 안: {tools} 확인",
        "render_container_missing": "컨테이너 안인데 {tools}을(를) 찾지 못했다",
        "render_container_fix": "앱 이미지가 덜 만들어졌다. deploy/docker/Dockerfile로 다시 만든다.",
        "render_ok": "Docker {version}이(가) 응답한다",
        "render_ok_image": "Docker {version}이(가) 응답하고, 조판 이미지가 만들어져 있다",
        "render_ok_noimage": "Docker {version}이(가) 응답한다. 조판 이미지는 첫 빌드에서 만든다(몇 분 걸린다)",
        "render_nodocker": "Docker를 찾지 못했다. 문서는 Docker 컨테이너에서 조판한다",
        "render_nodocker_fix_linux": "Docker Engine을 설치하고(https://docs.docker.com/engine/install/), 내 사용자를 docker 그룹에 넣는다: sudo usermod -aG docker $USER",
        "render_nodocker_fix_mac": "Docker Desktop을 설치하고(https://docs.docker.com/desktop/setup/install/mac-install/) 켠다.",
        "render_nodocker_fix_win": "WSL 2와 함께 Docker Desktop을 설치하고(https://docs.docker.com/desktop/setup/install/windows-install/), Offerowl은 WSL 안에서 실행한다.",
        "render_down": "Docker는 설치되어 있지만 엔진이 응답하지 않는다",
        "render_down_fix_linux": "켠다: sudo systemctl start docker (permission denied가 나오면 sudo usermod -aG docker $USER 뒤 다시 로그인한다).",
        "render_down_fix_other": "Docker Desktop을 켜고 실행 중이라고 나올 때까지 기다린다.",
        "render_nobash": "bash를 찾지 못했다. 컨테이너를 띄우는 render/run.sh가 bash 스크립트다",
        "render_nobash_fix": "Windows에서는 Offerowl을 WSL 안에서 실행하고, 그 밖에는 bash를 설치한다.",
        "render_container_windows": "OFFEROWL_RENDERER=container지만 Windows에서는 컨테이너를 띄울 수 없다. render/run.sh가 셸 스크립트다",
        "render_container_windows_fix": "OFFEROWL_RENDERER를 비우거나 html로 두어 Chrome이나 Edge로 조판하거나, WSL 안에서 Offerowl을 실행한다.",
        "render_bad_choice": "OFFEROWL_RENDERER가 {value}이다. 조판 방식이 아니다",
        "render_bad_choice_fix": "OFFEROWL_RENDERER를 container(Docker)나 html(이 PC의 Chrome이나 Edge)로 정하거나, 지워서 Docker가 있으면 Docker로, 없으면 브라우저로 조판한다.",
        "render_html_ok": "브라우저 조판이 준비되어 있다: {browser}({kind}), Node.js {node}",
        "render_html_missing": "OFFEROWL_RENDERER=html인데 이 PC에 없는 것: {what}",
        "render_html_unknown": "OFFEROWL_RENDERER=html인데 이 Offerowl에는 물어볼 브라우저 조판이 없다",
        "render_html_unknown_fix": "OFFEROWL_RENDERER를 지워 Docker로 조판하거나, 브라우저 조판이 든 버전을 설치한다.",
        "render_try_html": "또는 Docker 없이 이 PC의 {kind}로 조판한다: OFFEROWL_RENDERER=html 로 정한다.",
        "need_browser": "브라우저",
        "need_node": "Node.js",
        "need_pillow": "Pillow",
        "need_fonts": "글꼴 {names}",
        "html_fix_browser": "Microsoft Edge나 Google Chrome을 설치한다(또는 OFFEROWL_BROWSER가 Chromium 계열 브라우저를 가리키게 한다).",
        "html_fix_node": "https://nodejs.org/ 에서 Node.js 22 이상을 설치한다.",
        "html_fix_pillow": "Pillow를 설치한다: python3 -m pip install pillow",
        "html_fix_fonts": "Offerowl을 다시 설치한다. 글꼴 {names}은(는) 설치본에 들어 있다.",
        "browser_found": "{names}",
        "browser_playwright": "Python용 Playwright가 설치되어 있다",
        "browser_none": "Chromium 계열 브라우저도 Playwright도 찾지 못했다",
        "browser_none_fix": "Chromium, Google Chrome, Microsoft Edge 중 하나를 설치한다. 면접 화면 검사에는 이것도 필요하다: python3 -m pip install playwright && python3 -m playwright install chromium",
        "browser_default": "패널을 열 기본 브라우저: {name}",
        "browser_nodefault": "패널을 열 기본 브라우저가 없다",
        "browser_nodefault_fix": "브라우저에서 http://127.0.0.1:{port} 을 직접 연다.",
        "ai_in_use": "쓰는 것: {name} ({why})",
        "ai_claude_in": "Claude Code에 로그인되어 있다",
        "ai_claude_out": "Claude Code는 설치되어 있지만 로그아웃 상태다",
        "ai_claude_unknown": "Claude Code가 설치되어 있다(로그인 상태를 읽지 못했다)",
        "ai_codex_in": "Codex에 로그인되어 있다",
        "ai_codex_out": "Codex는 설치되어 있지만 로그아웃 상태다",
        "ai_codex_unknown": "Codex가 설치되어 있다(로그인했는지는 codex의 login status로 본다)",
        "ai_url_up": "로컬 모델 서버 {url}이(가) 응답한다",
        "ai_url_down": "로컬 모델 서버 {url}이(가) 응답하지 않는다",
        "ai_none_set": "AI 백엔드가 준비되지 않았다. AI 단계는 멈추고 사실은 직접 채운다",
        "ai_url_unused": "로컬 모델 서버 주소는 있지만 OFFEROWL_LLM을 정하지 않아 명령줄은 쓰지 않는다",
        "ai_fix_unused": "OFFEROWL_LLM=openai-compat 로 정한다(패널의 설정 메뉴는 패널에 대해 이미 그렇게 한다).",
        "ai_no_url": "OFFEROWL_LLM_URL을 정하지 않았다",
        "ai_chosen_off": "백엔드가 none이다. AI 단계는 멈추고 사실은 직접 채운다",
        "ai_chosen_unusable": "고른 백엔드 {name}을(를) 쓸 수 없다: {why}",
        "ai_fix": "Claude Code(claude auth login)나 Codex(codex login)에 로그인하거나, 로컬 모델 서버를 켜고 OFFEROWL_LLM=openai-compat OFFEROWL_LLM_URL=http://127.0.0.1:11434 OFFEROWL_LLM_MODEL=<모델> 로 정한다.",
        "ai_fix_claude": "로그인: claude auth login",
        "ai_fix_codex": "로그인: codex login",
        "ai_fix_url": "모델 서버를 켜거나, OFFEROWL_LLM_URL(또는 패널 설정의 주소)을 고친다.",
        "ai_why_panel": "패널 설정",
        "ai_why_env": "{var}로 정함",
        "ai_why_default": "기본 순서",
        "ai_why_argument": "인자",
        "ai_why_none": "설치된 것이 없음",
        "fonts_ok": "Pretendard가 {path}에 있다",
        "fonts_missing": "{path}에 없는 것: {names}",
        "fonts_fix": "Offerowl을 다시 설치한다. 글꼴은 설치본에 들어 있다.",
        "port_free": "{port} 비어 있다",
        "port_mine": "{port}은(는) 실행 중인 Offerowl이 쓴다",
        "port_busy": "{port}은(는) 다른 프로그램이 쓴다",
        "port_busy_fix": "포트 {port}을(를) 쓰는 프로그램을 끄거나, 패널을 다른 포트로 시작한다: offerowl panel --port <번호>.",
        "poppler_ok": "{reader}로 PDF를 읽는다",
        "poppler_missing": "PDF를 읽을 도구가 없다. 옛 PDF 읽기, 쪽 미리보기, 검사에 poppler나 pypdfium2가 필요하다",
        "poppler_fix_linux": "poppler(sudo apt install poppler-utils)나 pypdfium2(Offerowl이 설치된 곳에서 pip install pypdfium2 pillow)를 설치한다",
        "poppler_fix_mac": "poppler(brew install poppler)나 pypdfium2(Offerowl이 설치된 곳에서 pip install pypdfium2 pillow)를 설치한다",
        "poppler_fix_win": "pypdfium2를 설치한다: Offerowl이 설치된 곳에서 pip install pypdfium2 pillow. 데스크톱 앱에는 이미 들어 있다.",
        "sum_ready": "결과: 주의 {warns}개, 문제 없음. Offerowl이 문서를 만들 수 있다.",
        "sum_notready": "결과: 문제 {fails}개, 주의 {warns}개. 패널은 켜지지만 실패 줄을 고치기 전에는 문서를 만들 수 없다.",
        "bad_only": "모르는 검사 이름: {names}. 선택지: {choices}",
        "usage_only": "이 검사만 한다(쉼표로 구분: {choices})",
        "usage_json": "결과를 JSON으로 출력한다",
        "usage_desc": "Offerowl이 이 PC에서 필요로 하는 것을 점검하고, 빠진 것은 어떻게 할지 알려 준다.",
    },
}


def t(key: str, **kw) -> str:  # every person-facing string goes through this one call
    """A message of this program in the current language"""
    return llm.message(MSG, key, **kw)


@dataclass
class Check:  # one row of the report
    key: str  # the stable name used by --only and --json
    status: str  # ok, warn or fail
    title: str  # the row's name, in the current language
    detail: str  # what was found, one line
    fix: str = ""  # what to do, one line; empty when the status is ok


def row(key: str, status: str, detail: str, fix: str = "") -> Check:  # keeps the title lookup in one place
    """A Check whose title comes from the message table"""
    return Check(key, status, t("t_" + key), detail, fix)


# ---------------------------------------------------------------- facts about this PC

def os_kind() -> str:  # fix lines differ by system
    """linux, mac or win"""
    return "win" if sys.platform == "win32" else "mac" if sys.platform == "darwin" else "linux"


def in_container() -> bool:  # the same test as the engine (src/resume.py: in_container)
    """True inside the Offerowl container, where the typesetting tools are called directly"""
    return Path("/.dockerenv").exists()


def data_dir() -> Path:  # the same rule as apps/panel/server.py and apps/desktop/app.py (tests/packaging compares them)
    """Where the settings, the workspace and the logs go (OFFEROWL_DATA_DIR overrides it)"""
    if os.environ.get("OFFEROWL_DATA_DIR"):  # a chosen folder (tests, a portable copy, the container) wins
        return Path(os.environ["OFFEROWL_DATA_DIR"]).expanduser()  # a ~ in the variable means the home folder
    if sys.platform == "win32":  # Windows keeps per-user app data under LOCALAPPDATA
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Offerowl"  # its usual place when unset
    if sys.platform == "darwin":  # macOS has its own place for app data
        return Path.home() / "Library" / "Application Support" / "Offerowl"  # where Mac apps keep their files
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "offerowl"  # Linux: the XDG rule


def port_from(variable: str, default: int) -> int:  # the same variables the panel reads
    """The port named by an environment variable, else `default`"""
    try:  # a typo in the variable must not stop the doctor
        return int(os.environ.get(variable) or default)
    except ValueError:  # not a number
        return default  # the default


def panel_port() -> int:  # the port the panel will use
    """OFFEROWL_PANEL_PORT, else 8797"""
    return port_from("OFFEROWL_PANEL_PORT", PANEL_PORT)


def version(places=None) -> str:  # shown in the head line
    """The version: the app image sets OFFEROWL_VERSION; a checkout and an installed package carry the one line that writes it
    (deploy/python/offerowl/__init__.py, which is the package's own __init__.py once installed), as the panel and the MCP server
    read it; package metadata only when neither is there. A build's leftover offerowl.egg-info beside a checkout names an older
    version, so it is never read first."""
    if os.environ.get("OFFEROWL_VERSION"):  # the image carries no package metadata, so it says which release it is
        return os.environ["OFFEROWL_VERSION"]
    here = Path(__file__).resolve()  # src/doctor.py, or offerowl/engine/src/doctor.py once installed
    if places is None:  # a checkout, then the package (a test names its own)
        places = (here.parents[1] / "deploy" / "python" / "offerowl" / "__init__.py", here.parents[2] / "__init__.py")
    for f in places:
        try:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8"))  # the version line
        except OSError:  # not there in this layout
            continue
        if m:
            return m.group(1)  # e.g. 0.6.0
    try:  # the metadata exists only for an installed package
        from importlib.metadata import PackageNotFoundError, version as installed  # standard library
        try:  # a checkout has no metadata
            return installed("offerowl")  # for example 0.6.0
        except PackageNotFoundError:  # not installed as a package
            return "checkout"  # a folder of source files
    except ImportError:  # a very old Python: cannot happen on 3.10+, kept so that the head line never fails
        return "checkout"


def writable_dir(path: Path) -> bool:  # tries to write, because permission bits miss read-only mounts
    """True when files can be created in `path`; for a folder that does not exist yet, when its nearest existing parent
    allows it. Nothing is left behind and no folder is created."""
    probe = path  # the folder to test
    while not probe.exists() and probe != probe.parent:  # walk up to something that exists
        probe = probe.parent  # the parent could hold the new folder
    if not probe.is_dir():  # a file is in the way
        return False  # nothing can be created under it
    if probe != path:  # the folder itself does not exist yet
        return os.access(probe, os.W_OK | os.X_OK)  # the parent's permission decides; no probe file in a folder of someone else's
    try:  # the folder exists: write for real
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".offerowl-probe-"):  # deleted when the block ends
            return True  # it took a file
    except OSError:  # permission denied, read-only, no space
        return False  # not writable


def free_gb(path: Path) -> float | None:  # the disk the folder is on
    """Free space in GB of the disk that holds `path` (or its nearest existing parent); None when unknown"""
    probe = path  # start at the folder
    while not probe.exists() and probe != probe.parent:  # the disk is the parent's when the folder is new
        probe = probe.parent  # one level up
    try:  # disk_usage can fail on odd mounts
        return round(shutil.disk_usage(probe).free / 1e9, 1)  # bytes to GB
    except OSError:  # cannot be read
        return None  # the caller leaves the number out


def run(cmd: list[str], timeout: float = 10, stdout_only: bool = False) -> tuple[int, str]:  # one place for the subprocess rules
    """(exit code, output) of a command; (-1, reason) when it cannot start or does not finish in time. The command's
    input is empty so nothing waits on the terminal. The output holds both streams unless `stdout_only` (for JSON)."""
    try:  # a missing program or a hung one must not stop the doctor
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)  # output is read, never shown
    except (OSError, subprocess.TimeoutExpired) as exc:  # not found, not executable, too slow
        return -1, type(exc).__name__  # the kind of failure is enough
    return r.returncode, (r.stdout or "") if stdout_only else (r.stdout or "") + (r.stderr or "")  # both streams


def hide_password(url: str) -> str:  # an address may carry user:password@
    """The address with any password cut out, safe to print"""
    parts = urllib.parse.urlsplit(url if "//" in url else "//" + url)  # a bare host:port parses as a netloc
    if parts.password is None and parts.username is None:  # nothing to hide
        return url  # as given
    host = parts.hostname or ""  # the host alone
    netloc = host + (f":{parts.port}" if parts.port else "")  # without user and password
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))  # rebuilt


# ---------------------------------------------------------------- the checks

def check_python() -> Check:
    need = ".".join(map(str, MIN_PYTHON))  # "3.10"
    have = platform.python_version()  # "3.10.12"
    if sys.version_info[:2] >= MIN_PYTHON:  # new enough
        return row("python", "ok", t("python_ok", version=have, path=sys.executable))
    return row("python", "fail", t("python_old", version=have, need=need), t("python_fix", need=need))


def check_data() -> Check:
    path = data_dir()  # where Offerowl keeps the person's files
    if not writable_dir(path):  # the panel could not save anything
        return row("data", "fail", t("data_bad", path=path), t("data_bad_fix"))
    free = free_gb(path)  # None when the disk cannot be read
    if free is not None and free < MIN_FREE_GB:  # nearly full
        return row("data", "warn", t("data_low", path=path, free=free), t("data_low_fix"))
    return row("data", "ok", t("data_ok", path=path, free=free if free is not None else "?"))


def check_engine() -> Check:
    out = ROOT / "output"  # the engine writes every build here, under its own folder
    if not writable_dir(out):  # a read-only install (a system site-packages, a mounted image)
        return row("engine", "fail", t("engine_bad", path=ROOT), t("engine_bad_fix"))
    return row("engine", "ok", t("engine_ok", path=ROOT))


@functools.lru_cache(maxsize=None)
def renderer_report() -> dict | None:
    """What each renderer needs and finds, from the browser renderer's own `doctor` command (src/render_html/render.py):
    {"html": {"ok", "needs", "found"}, "container": {...}}. None when this copy has no browser renderer or it did not answer.
    Asked once per run; it starts node and the browser to read their versions."""
    script = ROOT / "src" / "render_html" / "render.py"
    if not script.is_file():  # a copy from before the browser renderer
        return None
    code, out = run([sys.executable, str(script), "doctor"], timeout=90, stdout_only=True)
    try:  # a broken answer is no answer
        data = json.loads(out) if code == 0 else None
    except ValueError:
        data = None
    return data if isinstance(data, dict) and isinstance(data.get("html"), dict) else None


def renderer_choice() -> str:  # the engine's own rule (src/resume.py: renderer)
    """OFFEROWL_RENDERER in lower case; when unset or empty, the choice the engine makes on this PC"""
    value = llm.setting("RENDERER", "").strip().lower()  # what was chosen, if anything
    if value:  # a choice decides
        return value
    import resume  # src/resume.py, loaded when first needed: it holds the rule for a PC with no choice
    return resume.renderer()  # the container where Docker is here, else the browser where it can typeset


def check_libs() -> Check:
    if (ROOT / "node_modules" / "docx").is_dir():  # the resume writer's library, which the panel also asks for
        return row("libs", "ok", t("libs_ok"))
    if in_container():  # the image installs them when it is built
        return row("libs", "fail", t("libs_missing", path=ROOT), t("libs_image_fix"))
    if renderer_choice() == "html":  # no container: npm runs on this PC
        return row("libs", "fail", t("libs_missing", path=ROOT), t("libs_missing_fix_html", path=ROOT))
    run_sh = ROOT / "render" / "run.sh"  # starts the container that installs them
    return row("libs", "fail", t("libs_missing", path=ROOT), t("libs_missing_fix", command=f"OFFEROWL_NET=1 {run_sh} npm ci"))


def render_image_built(docker: str) -> bool:  # tells the first build (slow) from a later one
    """True when the image render/run.sh would use already exists (tagged by the md5 of the Dockerfile, as run.sh does)"""
    dockerfile = ROOT / "render" / "Dockerfile"  # the render image's recipe
    if not dockerfile.is_file():  # a tree without the recipe cannot have the image
        return False
    tag = hashlib.md5(dockerfile.read_bytes()).hexdigest()[:12]  # the rule of run.sh and src/resume.py
    code, _ = run([docker, "image", "inspect", f"offerowl-render:{tag}"], timeout=10)  # exists or not
    return code == 0  # 0: found


def html_needs_words(needs: list[str]) -> tuple[str, str]:
    """(what is missing, what to do), in words, for the browser renderer's list of needs. node_modules is left to the
    libraries row, which has the command"""
    words, fixes = [], []
    for need in needs:
        if need == "browser":
            words.append(t("need_browser"))
            fixes.append(t("html_fix_browser"))
        elif need == "node":
            words.append(t("need_node"))
            fixes.append(t("html_fix_node"))
        elif need == "pillow":
            words.append(t("need_pillow"))
            fixes.append(t("html_fix_pillow"))
        elif need.startswith("fonts:"):
            names = need.split(":", 1)[1]
            words.append(t("need_fonts", names=names))
            fixes.append(t("html_fix_fonts", names=names))
    return ", ".join(words), " ".join(fixes)


def check_render() -> Check:
    if in_container():  # the tools are called directly here
        missing = [x for x in CONTAINER_TOOLS if shutil.which(x) is None]  # what the image should hold
        if missing:
            return row("render", "fail", t("render_container_missing", tools=", ".join(missing)), t("render_container_fix"))
        return row("render", "ok", t("render_container", tools=", ".join(CONTAINER_TOOLS)))
    choice = renderer_choice()  # how the engine will typeset
    if choice not in ("container", "html"):  # a typo must not pick a renderer silently
        return row("render", "fail", t("render_bad_choice", value=choice), t("render_bad_choice_fix"))
    report = renderer_report()  # None in a copy without the browser renderer
    html = (report or {}).get("html") or {}
    html_ready = bool(report) and not [n for n in html.get("needs") or [] if n != "node_modules"]  # the libraries have their own row
    found = html.get("found") or {}
    if choice == "html":
        if report is None:
            return row("render", "fail", t("render_html_unknown"), t("render_html_unknown_fix"))
        if not html_ready:
            what, fix = html_needs_words(html.get("needs") or [])
            return row("render", "fail", t("render_html_missing", what=what), fix)
        browser = Path(found.get("browser") or "").name or "?"
        return row("render", "ok", t("render_html_ok", browser=browser, kind=found.get("kind") or "?", node=str(found.get("node_version") or "?").lstrip("v")))
    if sys.platform == "win32":  # the build refuses the container here (resume.sh): doctor says the same, not "ok"
        return row("render", "fail", t("render_container_windows"), t("render_container_windows_fix"))
    # the container renderer: Docker, with the browser renderer named as the other way when it would work
    alternative = t("render_try_html", kind=found.get("kind") or "browser") if html_ready else ""
    kind = os_kind()  # for the fix lines
    docker = shutil.which("docker")  # the program that starts the render container
    if docker is None:  # not installed
        return row("render", "fail", t("render_nodocker"), " ".join(x for x in (t("render_nodocker_fix_" + kind), alternative) if x))
    code, out = run([docker, "version", "--format", "{{.Server.Version}}"], timeout=15)  # asks the engine, not only the client
    if code != 0 or not out.strip():  # installed, but the engine is off or refuses this user
        fix = t("render_down_fix_linux" if kind == "linux" else "render_down_fix_other")
        return row("render", "fail", t("render_down"), " ".join(x for x in (fix, alternative) if x))
    ver = re.search(r"\d+(?:\.\d+)+", out)  # the version number inside the output
    ver = ver.group(0) if ver else out.strip()[:20]  # whatever Docker said, bounded
    if shutil.which("bash") is None:  # run.sh cannot start
        return row("render", "fail", t("render_nobash"), " ".join(x for x in (t("render_nobash_fix"), alternative) if x))
    built = render_image_built(docker)  # the first build is slow
    return row("render", "ok", t("render_ok_image" if built else "render_ok_noimage", version=ver))


def browser_paths() -> list[tuple[str, str]]:
    """(name, path) of the Chromium-based browsers found on PATH and in the places each system installs them"""
    found: dict[str, str] = {}  # real path to name, one entry per file (google-chrome is often a link to google-chrome-stable)
    for name in BROWSERS:  # the names a Linux package or a PATH entry uses
        path = shutil.which(name)  # on PATH
        if path:
            found.setdefault(os.path.realpath(path), name)
    extra: list[str] = []  # fixed install places
    if sys.platform == "darwin":  # macOS apps
        extra += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    if sys.platform == "win32":  # Windows keeps them under Program Files
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                extra += [str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                          str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")]
    if os.environ.get("OFFEROWL_BROWSER"):  # a browser the person points at
        extra.append(os.environ["OFFEROWL_BROWSER"])
    for path in extra:
        if Path(path).is_file():
            found.setdefault(os.path.realpath(path), Path(path).stem)
    for path in ((renderer_report() or {}).get("html", {}).get("found", {}).get("browsers") or []):  # what the browser renderer would find
        if Path(path).is_file():
            found.setdefault(os.path.realpath(path), "playwright-chromium" if "ms-playwright" in path else Path(path).stem)
    return [(name, path) for path, name in found.items()]


def check_browser() -> Check:
    names = sorted({name for name, _ in browser_paths()})  # which browsers
    try:  # Playwright is the optional driver of the interview page checks
        import importlib.util  # standard library
        playwright = importlib.util.find_spec("playwright") is not None  # installed or not, without importing it
    except (ImportError, ValueError):  # a broken installation
        playwright = False
    parts = []  # what to say
    if names:
        parts.append(t("browser_found", names=", ".join(names)))
    if playwright:
        parts.append(t("browser_playwright"))
    default = ""  # the browser the panel's --open uses
    if not in_container():  # a container has no desktop to open a page on; the person opens the published port
        try:
            default = webbrowser.get().name  # raises when there is none (a server with no desktop)
        except webbrowser.Error:
            default = ""
    if default:
        parts.append(t("browser_default", name=default))
    if not names and not playwright:  # nothing for the checks
        return row("browser", "warn", t("browser_none"), t("browser_none_fix"))
    if not default and not in_container():  # the panel's --open has nothing to open
        return row("browser", "warn", "; ".join(parts + [t("browser_nodefault")]), t("browser_nodefault_fix", port=panel_port()))
    return row("browser", "ok", "; ".join(parts))


def panel_settings() -> dict:  # what the panel saved from its menu
    """The panel's settings file as a dict ({} when there is none or it is broken)"""
    try:  # a missing or broken file means no saved choice
        data = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def codex_state() -> str | None:
    """'in', 'out' or None (cannot tell) from `codex login status`; None without a short answer in time"""
    cmd = llm.codex_cmd()  # codex, or the command OFFEROWL_CODEX_CMD names
    if not cmd or cmd[0] in ("npx", "npx.cmd"):  # npx may download the CLI first: too slow for a check
        return None
    code, out = run(cmd + ["login", "status"], timeout=15)  # local and quick
    if code == -1:  # did not start or did not answer
        return None
    if re.search(r"not logged in", out, re.I):  # the negative first: "not logged in" also contains "logged in"
        return "out"
    return "in" if re.search(r"logged in", out, re.I) else None


def url_up(url: str) -> bool:  # an OpenAI-compatible server lists its models at /v1/models
    """True when the model server answers at all (any HTTP status counts: a server that wants a key still runs)"""
    base = url.strip().rstrip("/")  # as the engine cleans it
    if not re.match(r"https?://", base):  # "localhost:11434" without a scheme
        base = "http://" + base
    base = re.sub(r"/v1$", "", base)  # an address written the OpenAI SDK way
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a local server needs no proxy
        with opener.open(base + "/v1/models", timeout=3):  # a quick look
            return True
    except urllib.error.HTTPError:  # the server answered with an error status: it is up
        return True
    except (OSError, ValueError):  # refused, unreachable, timed out, not an address
        return False


def check_ai() -> Check:
    saved = panel_settings()  # the panel's menu choices
    url = llm.setting("LLM_URL").strip() or str(saved.get("llm_url") or "").strip()  # the local server, from the environment or the panel
    avail = llm.available()  # presence of each backend, by the engine's own rules
    found: list[str] = []  # what exists, as sentences
    fixes: list[str] = []  # what to do about what is not ready
    ready: dict[str, bool] = {}  # backend to whether the AI steps can use it right now
    if avail["claude-code"][0]:  # the CLI is installed
        state = llm.claude_signed_in()  # True, False, or None when the CLI cannot tell
        found.append(t("ai_claude_in" if state else "ai_claude_out" if state is False else "ai_claude_unknown"))
        ready["claude-code"] = state is not False  # "cannot tell" still counts as usable, as the engine does
        if state is False:
            fixes.append(t("ai_fix_claude"))
    if avail["codex"][0]:  # Codex is installed
        state_codex = codex_state()  # 'in', 'out' or None
        found.append(t("ai_codex_in" if state_codex == "in" else "ai_codex_out" if state_codex == "out" else "ai_codex_unknown"))
        ready["codex"] = state_codex != "out"
        if state_codex == "out":
            fixes.append(t("ai_fix_codex"))
    if url:  # a local OpenAI-compatible server is named
        up = url_up(url)
        found.append(t("ai_url_up" if up else "ai_url_down", url=hide_password(url)))
        ready["openai-compat"] = up
        if not up:
            fixes.append(t("ai_fix_url"))
    name, source = llm.chosen()  # the backend the command line would use
    if source == "default" and str(saved.get("backend") or "auto") != "auto":  # the panel's menu choice stands in for the default order
        name, source = str(saved["backend"]), "panel"
    why = {"default": t("ai_why_default"), "argument": t("ai_why_argument"), "panel": t("ai_why_panel")}.get(source) \
        or t("ai_why_env", var=source)  # any other source is the name of an environment variable
    if name == "none":  # switched off, or nothing is installed
        if source == "default":  # the default order found nothing to use
            if url:  # an address is set, but the engine does not pick it by itself
                found.append(t("ai_url_unused"))
                return row("ai", "warn", "; ".join(found), t("ai_fix_unused"))
            return row("ai", "warn", "; ".join(found + [t("ai_none_set")]), t("ai_fix"))
        return row("ai", "ok", "; ".join(found + [t("ai_chosen_off")]))  # someone chose none: nothing is wrong
    if name not in ready:  # chosen, but not installed or no address
        reason = avail.get(name, (False, name))[1] if name != "openai-compat" else t("ai_no_url")
        return row("ai", "warn", "; ".join(found + [t("ai_chosen_unusable", name=name, why=reason)]), t("ai_fix"))
    detail = "; ".join(found + [t("ai_in_use", name=name, why=why)])  # what exists and which one is used
    if not ready[name]:  # chosen and present, but signed out or not answering
        return row("ai", "warn", detail, " ".join(fixes))
    return row("ai", "ok", detail)  # a chosen backend that works; another one being signed out is not a problem


def check_fonts() -> Check:
    folder = ROOT / "fonts"  # the fonts Offerowl ships (Pretendard, SIL OFL)
    missing = [f for f in FONT_FILES if not (folder / f).is_file()]  # the three the panel and the documents use
    if missing:
        return row("fonts", "fail", t("fonts_missing", path=folder, names=", ".join(missing)), t("fonts_fix"))
    return row("fonts", "ok", t("fonts_ok", path=folder))


def port_state(port: int) -> str:  # 'free', 'mine' or 'busy'
    """Whether something listens on 127.0.0.1:port, and if so whether it is Offerowl (its health answer says so)"""
    try:  # a refused connection means nothing listens
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        return "free"
    for path in ("/health", "/api/health"):  # the panel and the interview view each answer one of these
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
                body = json.loads(r.read() or b"{}")
            # the panel says app=offerowl; the interview view answers ok=true with its item count
            if isinstance(body, dict) and (body.get("app") == "offerowl" or (body.get("ok") is True and "items" in body)):
                return "mine"
        except (OSError, ValueError):  # not HTTP, not JSON, a 403 for the Host header, ...
            continue
    return "busy"


def check_ports() -> Check:
    states = {p: port_state(p) for p in (panel_port(),)}  # the panel's port: it serves the interview kit too, at /kit/<job>/
    busy = [p for p, s in states.items() if s == "busy"]  # taken by something else
    parts = [t("port_" + s, port=p) for p, s in states.items()]  # one phrase per port
    if busy:
        return row("ports", "warn", "; ".join(parts), t("port_busy_fix", port=busy[0]))
    return row("ports", "ok", "; ".join(parts))


def check_poppler() -> Check:
    import pdftools  # the module that reads PDFs, with poppler or PDFium
    if pdftools.reader():  # either one: the checks, the page previews and the interview kit can read a PDF here
        return row("poppler", "ok", t("poppler_ok", reader={"poppler": "poppler", "pdfium": "pypdfium2"}[pdftools.reader()]))
    return row("poppler", "warn", t("poppler_missing"), t("poppler_fix_" + os_kind()))


CHECKS = {  # name to function, in the order of the report
    "python": check_python, "data": check_data, "engine": check_engine, "libs": check_libs, "render": check_render,
    "browser": check_browser, "ai": check_ai, "fonts": check_fonts, "ports": check_ports, "poppler": check_poppler,
}


# ---------------------------------------------------------------- the report

def run_checks(only: list[str] | None = None) -> list[Check]:
    """The checks, in report order; `only` limits them to some names"""
    results = []  # one per check
    for name, fn in CHECKS.items():
        if only and name not in only:  # not asked for
            continue
        try:  # one broken check must not hide the others
            results.append(fn())
        except Exception as exc:  # a bug in a check: shown as a failed row, never a traceback
            results.append(Check(name, "warn", t("t_" + name), f"{type(exc).__name__}: {exc}"))
    return results


def summary(results: list[Check]) -> tuple[int, int]:
    """(warnings, failures)"""
    return (sum(r.status == "warn" for r in results), sum(r.status == "fail" for r in results))


def cells(text: str) -> int:  # Korean letters take two columns of a terminal
    """The width of `text` in terminal columns"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def pad(text: str, width: int) -> str:  # str.ljust counts letters, not columns
    """`text` followed by spaces up to `width` terminal columns"""
    return text + " " * max(0, width - cells(text))


def render(results: list[Check]) -> str:
    """The report as text"""
    lines = [t("head", version=version(), python=platform.python_version(), system=f"{platform.system()} {platform.machine()}")]
    if in_container():  # said once, under the head
        lines.append(t("in_container"))
    lines.append("")
    width = max(cells(r.title) for r in results) if results else 0  # titles line up
    for r in results:
        lines.append(f"  {t('mark_' + r.status)}  {pad(r.title, width)}  {r.detail}")
        if r.fix:  # the plain fix line sits under its row
            lines.append(f"  {'':4}  {pad('', width)}  {t('fix', text=r.fix)}")
    warns, fails = summary(results)
    lines += ["", t("sum_notready", fails=fails, warns=warns) if fails else t("sum_ready", warns=warns)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Korean words through a Windows console, a pipe or a file in cp1252: UTF-8 whatever the code page
        if hasattr(stream, "reconfigure"):  # a text stream of this Python, not a test's replacement
            stream.reconfigure(encoding="utf-8", errors="replace")
    choices = ", ".join(CHECKS)  # for the help and the error
    ap = argparse.ArgumentParser(prog="offerowl doctor", description=t("usage_desc"))
    ap.add_argument("--json", action="store_true", help=t("usage_json"))
    ap.add_argument("--only", help=t("usage_only", choices=choices))
    args = ap.parse_args(argv)  # exits with 2 on a wrong command line
    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
    unknown = [x for x in only or [] if x not in CHECKS]  # a typo must not pass for "all fine"
    if unknown:
        print(t("bad_only", names=", ".join(unknown), choices=choices), file=sys.stderr)
        return 2
    results = run_checks(only)
    warns, fails = summary(results)
    if args.json:  # for scripts: the same rows plus the totals
        print(json.dumps({"version": version(), "python": platform.python_version(), "platform": f"{platform.system()} {platform.machine()}",
                          "container": in_container(), "checks": [asdict(r) for r in results],
                          "summary": {"warn": warns, "fail": fails}}, ensure_ascii=False, indent=1))
    else:
        print(render(results))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
