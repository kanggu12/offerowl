"""Tests of the app image's recipe (deploy/docker): the Dockerfile, the compose file and the entrypoint, without building the
image (tests/packaging/image_smoke.sh builds and starts it). They read the files, ask Docker to parse them where Docker is
installed, and run the entrypoint's own functions on throwaway folders.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import json  # the panel's settings file
import os  # environment
import pathlib  # paths
import re  # read the Dockerfile
import unittest  # the test framework
from unittest import mock  # patch the entrypoint's helpers

from pkg_support import DOCKER_DIR, ROOT, clean_env, load_module, need_yaml, package_version, run, tmpdir, tool, yaml

DOCKERFILE = (DOCKER_DIR / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = DOCKER_DIR / "compose.yaml"


def instructions(text: str) -> list:
    """The Dockerfile's instructions as (KEYWORD, rest of the line), with continuation lines joined and comments dropped"""
    joined = re.sub(r"\\\n", " ", "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#")))
    return [(line.split(None, 1)[0].upper(), line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else "")
            for line in joined.splitlines() if line.strip()]


def run_blocks(text: str) -> list:
    """The RUN instructions, with all white space squeezed, so that a re-wrapped line does not count as a change"""
    return [re.sub(r"\s+", " ", rest).strip() for kw, rest in instructions(text) if kw == "RUN"]


class DockerfileTest(unittest.TestCase):
    def setUp(self):
        self.ins = instructions(DOCKERFILE)

    def values(self, keyword: str) -> list:
        return [rest for kw, rest in self.ins if kw == keyword]

    def test_it_starts_from_the_render_images_base(self):
        base = [r for r in self.values("FROM")]
        self.assertEqual(base, re.findall(r"^FROM (.+)$", (ROOT / "render" / "Dockerfile").read_text(encoding="utf-8"), re.M))

    def test_the_tool_layers_are_the_render_images_word_for_word(self):
        # identical layers come out of the build cache when render/run.sh's image was built on this machine, and the typeset
        # output of the container and of render/run.sh cannot drift apart
        render = run_blocks((ROOT / "render" / "Dockerfile").read_text(encoding="utf-8"))
        app = run_blocks(DOCKERFILE)
        self.assertGreaterEqual(len(render), 3)
        self.assertEqual(app[:len(render)], render)

    def test_it_runs_as_a_fixed_user_that_is_not_root(self):
        users = self.values("USER")
        self.assertEqual(users, ["10001:10001"])
        self.assertEqual(self.ins[[kw for kw, _ in self.ins].index("USER")][0], "USER")
        # nothing that needs root comes after USER
        after = self.ins[[kw for kw, _ in self.ins].index("USER") + 1:]
        self.assertFalse([kw for kw, _ in after if kw in ("RUN", "COPY", "ADD")], after)
        self.assertIn("useradd --uid 10001 --gid 10001", " ".join(run_blocks(DOCKERFILE)))

    def test_it_has_a_health_check_that_asks_the_panels_health_with_a_host_it_accepts(self):
        health = self.values("HEALTHCHECK")
        self.assertEqual(len(health), 1)
        self.assertIn("127.0.0.1", health[0])  # the Host header the panel accepts
        self.assertIn("/health", health[0])
        self.assertIn("OFFEROWL_PANEL_PORT", health[0])
        self.assertIn("--start-period", health[0])

    def test_tini_is_the_first_process_and_the_entrypoint_starts_the_panel_by_default(self):
        self.assertTrue(self.values("ENTRYPOINT")[0].startswith('["tini", "--"'))
        self.assertEqual(self.values("CMD"), ['["panel"]'])

    def test_it_exposes_the_panel_only(self):
        self.assertEqual(self.values("EXPOSE"), ["8797"])  # the interview kit is served by the panel, at /kit/<job>/

    def test_the_engine_finds_the_marker_of_the_render_container(self):
        self.assertIn("touch /.dockerenv", " ".join(run_blocks(DOCKERFILE)))
        self.assertIn("WORKDIR /work", [f"{kw} {rest}" for kw, rest in self.ins])  # src/fonts.sh names /work

    def test_the_settings_the_container_needs_are_set(self):
        env = " ".join(self.values("ENV"))
        for setting in ("HOME=/tmp", "OFFEROWL_DATA_DIR=/data", "OFFEROWL_PANEL_PORT=8797",
                        "OFFEROWL_DESKTOP=/data/export", "PYTHONDONTWRITEBYTECODE=1"):
            self.assertIn(setting, env)

    def test_no_floating_tag_and_no_secret(self):
        self.assertNotIn(":latest", DOCKERFILE)
        for word in ("password", "token", "secret", "api_key"):
            self.assertNotIn(word, DOCKERFILE.lower().replace("no secret", ""), word)

    def test_the_label_and_the_setting_name_the_version_of_the_package(self):
        self.assertIn(f'org.opencontainers.image.version="{package_version()}"', DOCKERFILE)
        self.assertIn(f"OFFEROWL_VERSION={package_version()}", " ".join(self.values("ENV")))

    def test_buildkit_finds_no_fault_with_it(self):
        docker = tool(self, "docker")
        r = run([docker, "build", "--check", "-f", str(DOCKER_DIR / "Dockerfile"), str(ROOT)], timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("WARN", r.stdout + r.stderr)


class ComposeTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)
        self.compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        self.app = self.compose["services"]["app"]

    def test_the_project_is_named_for_the_app(self):
        self.assertEqual(self.compose["name"], "offerowl-app")  # its containers, network and volumes are named after it

    def test_the_panels_port_is_opened_on_the_loopback_only_with_one_number_on_both_sides(self):
        self.assertEqual(len(self.app["ports"]), 1)  # the panel's: it serves the interview kit too, at /kit/<job>/
        for port in self.app["ports"]:
            self.assertTrue(str(port).startswith("127.0.0.1:"), port)
            # the panel answers only requests whose Host header names its own port, so the published port is the
            # container's: the same variable and default on both sides
            match = re.fullmatch(r"127\.0\.0\.1:(\$\{(\w+):-(\d+)\}):(\$\{\w+:-\d+\})", port)
            self.assertTrue(match, port)
            self.assertEqual(match.group(1), match.group(4))
        variables = {re.search(r"\$\{(\w+):-(\d+)\}", p).groups() for p in self.app["ports"]}
        self.assertEqual(variables, {("OFFEROWL_PANEL_PORT", "8797")})  # the panel's port only: it serves the interview kit too
        self.assertIn("OFFEROWL_PANEL_PORT=${OFFEROWL_PANEL_PORT:-8797}", self.app["environment"])

    def test_it_is_hardened(self):
        self.assertIs(self.app["read_only"], True)
        self.assertEqual(self.app["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", self.app["security_opt"])
        self.assertNotIn("privileged", self.app)
        self.assertNotIn("network_mode", self.app)
        self.assertNotIn("cap_add", self.app)
        self.assertEqual(self.app["restart"], "on-failure:3")  # a crash comes back, a few times at most; a stop stays a stop
        self.assertTrue(any(t.startswith("/tmp:") for t in self.app["tmpfs"]))
        self.assertIn("pids_limit", self.app)

    def test_the_files_live_in_volumes(self):
        targets = [v.rsplit(":", 1)[1] for v in self.app["volumes"]]  # "source:target"; the source may hold a ${VAR:-default}
        self.assertEqual(sorted(targets), ["/data", "/work/output"])
        self.assertEqual(sorted(self.compose["volumes"]), ["offerowl-data", "offerowl-output"])
        self.assertIn("${OFFEROWL_DATA:-offerowl-data}:/data", self.app["volumes"])

    def test_the_ai_settings_are_passed_through_and_never_given_a_default(self):
        env = [e for e in self.app["environment"] if "=" not in e]
        for name in ("OFFEROWL_LLM", "OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL", "OFFEROWL_LLM_KEY", "OFFEROWL_LANG"):
            self.assertIn(name, env)
        self.assertNotIn("OFFEROWL_LLM_KEY=", COMPOSE.read_text(encoding="utf-8").replace("OFFEROWL_LLM_KEY=<key>", ""))

    def test_it_builds_from_the_repository_root_with_this_folders_dockerfile(self):
        build = self.app["build"]
        self.assertEqual((COMPOSE.parent / build["context"]).resolve(), ROOT)
        self.assertTrue((ROOT / build["dockerfile"]).is_file())
        self.assertEqual(build["dockerfile"], "deploy/docker/Dockerfile")

    def test_docker_parses_it_and_the_service_keeps_its_hardening(self):
        docker = tool(self, "docker")
        env = clean_env(OFFEROWL_PANEL_PORT="18797")
        r = run([docker, "compose", "-f", str(COMPOSE), "config", "--format", "json"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        service = json.loads(r.stdout)["services"]["app"]
        self.assertEqual(service["read_only"], True)
        self.assertEqual(service["user"], "10001:10001")
        self.assertEqual(sorted(p["published"] for p in service["ports"]), ["18797"])
        self.assertEqual({p["host_ip"] for p in service["ports"]}, {"127.0.0.1"})
        self.assertEqual(service["image"], "offerowl-app:local")
        published = run([docker, "compose", "-f", str(COMPOSE), "config", "--format", "json"],
                        env=clean_env(OFFEROWL_APP_IMAGE="ghcr.io/example/offerowl-app", OFFEROWL_APP_TAG="9.9.9"))
        self.assertEqual(json.loads(published.stdout)["services"]["app"]["image"], "ghcr.io/example/offerowl-app:9.9.9")


class EntrypointTest(unittest.TestCase):
    def setUp(self):
        self.ep = load_module("offerowl_entrypoint", DOCKER_DIR / "entrypoint.py")
        self.data = tmpdir(self) / "data"
        self.data.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("OFFEROWL_")}
        patcher = mock.patch.dict(os.environ, {**env, "OFFEROWL_DATA_DIR": str(self.data), "OFFEROWL_LANG": "en"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def settings(self) -> dict:
        return json.loads((self.data / "settings.json").read_text(encoding="utf-8"))

    def test_a_first_start_with_nothing_set_turns_the_agent_off(self):
        self.ep.seed_settings({})
        self.assertEqual(self.settings(), {"backend": "none"})  # the image has no agent CLI: "auto" would show one that cannot be installed

    def test_the_environment_writes_the_backend_the_address_and_the_model(self):
        env = {"OFFEROWL_LLM": "openai-compat", "OFFEROWL_LLM_URL": "http://models.example.invalid:11434", "OFFEROWL_LLM_MODEL": "m"}
        self.assertEqual(self.ep.seed_settings(env), {"backend": "openai-compat", "llm_url": "http://models.example.invalid:11434", "llm_model": "m"})
        self.assertEqual(self.settings()["llm_model"], "m")

    def test_an_address_alone_means_the_local_server(self):
        self.ep.seed_settings({"OFFEROWL_LLM_URL": "models:11434"})
        self.assertEqual(self.settings()["backend"], "openai-compat")

    def test_what_the_person_saved_is_kept_and_the_environment_wins_only_for_what_it_names(self):
        (self.data / "settings.json").write_text(json.dumps({"backend": "openai-compat", "lang": "ko", "llm_url": "http://old", "llm_model": "old"}))
        self.ep.seed_settings({})  # nothing named: nothing changes
        self.assertEqual(self.settings(), {"backend": "openai-compat", "lang": "ko", "llm_url": "http://old", "llm_model": "old"})
        self.ep.seed_settings({"OFFEROWL_LLM_URL": "http://new"})  # the new address replaces the old; the rest stays
        self.assertEqual(self.settings(), {"backend": "openai-compat", "lang": "ko", "llm_url": "http://new", "llm_model": "old"})
        self.ep.seed_settings({"OFFEROWL_LLM": "none"})
        self.assertEqual(self.settings()["backend"], "none")
        self.assertEqual(self.settings()["lang"], "ko")

    def test_the_key_is_never_written_to_disk(self):
        self.ep.seed_settings({"OFFEROWL_LLM": "openai-compat", "OFFEROWL_LLM_URL": "http://x", "OFFEROWL_LLM_KEY": "s3cr3t"})
        for f in self.data.rglob("*"):
            if f.is_file():
                self.assertNotIn("s3cr3t", f.read_text(encoding="utf-8"))

    def test_a_backend_that_is_not_in_the_image_is_ignored_with_a_message(self):
        with mock.patch("sys.stderr") as err:
            self.ep.seed_settings({"OFFEROWL_LLM": "gpt-nine"})
        self.assertTrue(any("gpt-nine" in str(c) for c in err.write.call_args_list))
        self.assertEqual(self.settings(), {"backend": "none"})

    def test_a_broken_settings_file_is_left_alone_and_said_so(self):
        (self.data / "settings.json").write_text("{not json")
        with mock.patch("sys.stderr") as err:
            self.assertEqual(self.ep.seed_settings({"OFFEROWL_LLM": "none"}), {})
        self.assertIn("not valid JSON", "".join(str(c) for c in err.write.call_args_list))
        self.assertEqual((self.data / "settings.json").read_text(), "{not json")

    def test_a_restart_does_not_touch_an_unchanged_file(self):
        self.ep.seed_settings({"OFFEROWL_LLM": "none"})
        before = (self.data / "settings.json").stat().st_mtime_ns
        self.ep.seed_settings({"OFFEROWL_LLM": "none"})
        self.assertEqual((self.data / "settings.json").stat().st_mtime_ns, before)

    def test_the_data_folders_are_made_and_a_folder_that_cannot_be_written_is_explained(self):
        with mock.patch.object(self.ep, "ROOT", self.data.parent):  # output/ under a throwaway root
            (self.data.parent / "output").mkdir(exist_ok=True)
            self.assertTrue(self.ep.prepare_folders())
        for name in ("workspace", "logs", "export"):
            self.assertTrue((self.data / name).is_dir(), name)
        with mock.patch.object(self.ep, "writable", return_value=False), mock.patch("sys.stderr") as err:
            self.assertFalse(self.ep.prepare_folders())
        self.assertIn("OFFEROWL_UID", "".join(str(c) for c in err.write.call_args_list))

    def test_the_command_decides_what_the_container_becomes(self):
        panel = self.ep.command_for([])
        self.assertEqual(panel[1:], [str(ROOT / "apps" / "panel" / "server.py"), "--host", "0.0.0.0", "--port", "8797"])
        os.environ["OFFEROWL_PANEL_PORT"] = "18797"
        self.assertEqual(self.ep.command_for(["panel", "--open"])[-3:], ["--port", "18797", "--open"])
        self.assertEqual(self.ep.command_for(["doctor", "--json"])[1:], [str(ROOT / "src" / "doctor.py"), "--json"])
        self.assertEqual(self.ep.command_for(["build", "p.json"])[1:], [str(ROOT / "offerowl"), "build", "p.json"])
        self.assertEqual(self.ep.command_for(["no-such-command-xyz"])[1:], [str(ROOT / "offerowl"), "no-such-command-xyz"])  # the launcher names it unknown
        self.assertEqual(self.ep.command_for(["sh", "-c", "true"]), ["sh", "-c", "true"])  # an ordinary program is started as it is

    def test_both_languages_have_the_same_messages(self):
        en, ko = self.ep.MSG["en"], self.ep.MSG["ko"]
        self.assertEqual(sorted(en), sorted(ko))
        for key in en:
            self.assertEqual(set(re.findall(r"\{(\w+)\}", en[key])), set(re.findall(r"\{(\w+)\}", ko[key])), key)

    def test_it_is_started_with_python_and_is_executable_in_a_checkout(self):
        self.assertTrue((DOCKER_DIR / "entrypoint.py").read_text(encoding="utf-8").startswith("#!/usr/bin/env python3"))
        self.assertIn(pathlib.Path(self.ep.__file__).name, DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
