"""Tests of the container recipe without starting a container: run.sh in dry-run mode prints the docker command it would
run.

Run: python3 -m unittest discover -s tests/cli -v
"""
import hashlib  # the image tag is the md5 of the Dockerfile
import os  # a folder any user may write
import pathlib  # paths
import re  # tag format
import shutil  # is docker installed
import subprocess  # run run.sh
import tempfile  # a throwaway assets folder
import unittest  # the test framework

from support import ROOT, clean_env

RUN_SH = ROOT / "render" / "run.sh"


DOCKER_CPUS = "32"  # the CPUs the made-up docker below says it has, unless a test says otherwise


def dry_run(*extra_args: str, docker_cpus: str = DOCKER_CPUS, **env: str) -> subprocess.CompletedProcess:
    """run.sh with OFFEROWL_DRY_RUN=1: prints the docker command, one word per line. The only docker it asks is a made-up one
    that answers `docker info` with `docker_cpus` CPUs, so the caps do not depend on this PC"""
    with tempfile.TemporaryDirectory() as bin_:
        fake = pathlib.Path(bin_) / "docker"
        fake.write_text(f'#!/bin/sh\nif [ "$1" = info ]; then echo {docker_cpus}; fi\nexit 0\n', encoding="utf-8")
        fake.chmod(0o755)
        base = clean_env(OFFEROWL_DRY_RUN="1", **env)
        base["PATH"] = bin_ + ":" + base.get("PATH", "")
        return subprocess.run(["bash", str(RUN_SH), *(extra_args or ("true",))], capture_output=True, text=True, encoding="utf-8",
                              env=base, timeout=60)


def words(r: subprocess.CompletedProcess) -> list:
    """The printed command as a list of words"""
    return r.stdout.splitlines()


def after(command: list, flag: str) -> str:
    """The word that follows `flag` in the command"""
    return command[command.index(flag) + 1]


class RunShTest(unittest.TestCase):
    def test_the_image_is_named_offerowl_render_with_the_dockerfile_hash(self):
        r = dry_run()
        self.assertEqual(r.returncode, 0, r.stderr)
        tag = hashlib.md5((ROOT / "render" / "Dockerfile").read_bytes()).hexdigest()[:12]
        self.assertIn(f"offerowl-render:{tag}", words(r))
        self.assertRegex(tag, r"^[0-9a-f]{12}$")

    def test_the_container_name_starts_with_offerowl(self):
        self.assertRegex(after(words(dry_run()), "--name"), r"^offerowl-render-\d+$")

    def test_the_command_is_passed_through_after_the_image(self):
        cmd = words(dry_run("node", "--version"))
        self.assertEqual(cmd[-2:], ["node", "--version"])

    def test_defaults_are_closed_network_and_the_resource_caps(self):
        cmd = words(dry_run())
        self.assertEqual(after(cmd, "--network"), "none")
        self.assertEqual(after(cmd, "--cpus"), "6")
        self.assertEqual(after(cmd, "--memory"), "4g")
        self.assertIn(f"{ROOT}:/work", cmd)  # the repository is the working folder

    def test_no_assets_mount_unless_offerowl_assets_is_set(self):
        self.assertFalse([w for w in words(dry_run()) if "/offerowl-assets" in w])

    def test_offerowl_assets_is_mounted_read_only(self):
        with tempfile.TemporaryDirectory() as assets:
            cmd = words(dry_run(OFFEROWL_ASSETS=assets))
            self.assertIn(f"{pathlib.Path(assets).resolve()}:/offerowl-assets:ro", cmd)

    def test_an_assets_path_that_is_not_a_folder_is_an_error(self):
        # Docker would quietly create it as an empty folder; better to stop.
        r = dry_run(OFFEROWL_ASSETS="/nonexistent/offerowl-assets")
        self.assertEqual(r.returncode, 2)
        self.assertIn("OFFEROWL_ASSETS", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_the_network_setting(self):
        self.assertEqual(after(words(dry_run(OFFEROWL_NET="1")), "--network"), "bridge")
        self.assertEqual(after(words(dry_run(OFFEROWL_NET="0")), "--network"), "none")

    def test_the_caps(self):
        cmd = words(dry_run(OFFEROWL_CPUS="8", OFFEROWL_MEM="2g"))
        self.assertEqual((after(cmd, "--cpus"), after(cmd, "--memory")), ("8", "2g"))

    def test_the_cpu_cap_is_never_more_than_docker_has(self):
        # Docker refuses a cap above its CPUs: a four-CPU PC (or a CI runner) would get no container at all
        self.assertEqual(after(words(dry_run(docker_cpus="4")), "--cpus"), "4")  # the default of six, lowered
        self.assertEqual(after(words(dry_run(docker_cpus="4", OFFEROWL_CPUS="8")), "--cpus"), "4")  # a setting above it too
        self.assertEqual(after(words(dry_run(docker_cpus="4", OFFEROWL_CPUS="2.5")), "--cpus"), "2.5")  # one below it stays

    def test_scripts_in_the_container_see_a_setting(self):
        cmd = words(dry_run(OFFEROWL_THEME="mono", OFFEROWL_THEME_FILE="/work/themes.json"))
        for pair in ("OFFEROWL_THEME=mono", "OFFEROWL_THEME_FILE=/work/themes.json"):
            self.assertIn(pair, cmd)

    def test_a_blind_edition_and_the_pdf_reader_reach_the_container(self):
        # the masking runs in the scripts inside the container: a setting left on the host printed every name it should cover
        cmd = words(dry_run(OFFEROWL_BLIND="1", OFFEROWL_BLIND_LANG="en", OFFEROWL_PDF_READER="pdfium"))
        for pair in ("OFFEROWL_BLIND=1", "OFFEROWL_BLIND_LANG=en", "OFFEROWL_PDF_READER=pdfium"):
            self.assertIn(pair, cmd)

    def test_language_reaches_the_container(self):
        self.assertIn("OFFEROWL_LANG=ko", words(dry_run(OFFEROWL_LANG="ko")))

    def test_nothing_is_passed_that_was_not_set(self):
        joined = " ".join(words(dry_run()))
        for name in ("THEME", "FRESH", "NOLOGOS", "PROFILE", "LANG", "BLIND", "PDF_READER"):
            self.assertNotIn(name + "=", joined, name)

    def test_the_script_passes_bash_and_shellcheck(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(RUN_SH)]).returncode, 0)
        if shutil.which("shellcheck"):  # installed on the CI runner; optional on a developer machine
            r = subprocess.run(["shellcheck", str(RUN_SH)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


def render_image() -> str:
    """The render container's image as run.sh names it, or "" when Docker or the image is not here."""
    if not shutil.which("docker"):
        return ""
    tag = hashlib.md5(RUN_SH.with_name("Dockerfile").read_bytes()).hexdigest()[:12]  # run.sh's rule
    r = subprocess.run(["docker", "image", "inspect", f"offerowl-render:{tag}"], capture_output=True)
    return f"offerowl-render:{tag}" if r.returncode == 0 else ""


@unittest.skipUnless(render_image(), "the render container's image is not built here (render/run.sh builds it)")
class ContainerUserTest(unittest.TestCase):
    """The container runs as the person's own user id. The image lists only 1000 (node) in /etc/passwd: for any other id (a
    Mac's 501, a CI runner's 1001) LibreOffice finds no home and stopped every resume and cover letter at its PDF."""

    def test_libreoffice_starts_for_a_user_the_image_does_not_know(self):
        cmd = words(dry_run())  # the docker command run.sh runs
        env = [x for e in (cmd[i + 1] for i, w in enumerate(cmd[:-1]) if w == "-e") for x in ("-e", e)]  # the settings it hands over
        with tempfile.TemporaryDirectory() as d:  # a folder the made-up user may write
            os.chmod(d, 0o777)
            (pathlib.Path(d) / "a.txt").write_text("hello", encoding="utf-8")  # a document to convert
            r = subprocess.run(["docker", "run", "--rm", "--network", "none", "-u", "4242:4242", *env, "-v", f"{d}:/w", "-w", "/w",
                                render_image(), "soffice", "--headless", "--convert-to", "pdf", "--outdir", "/w", "/w/a.txt"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            self.assertTrue((pathlib.Path(d) / "a.pdf").is_file(), r.stdout + r.stderr)  # LibreOffice started and printed it


if __name__ == "__main__":
    unittest.main()
