"""Tests of the GitHub workflows (.github/workflows): they parse, they are consistent with each other and with the files they
call, every action is pinned, nothing interpolates untrusted text into a script, and what a release needs of them is there:
desktop builds on the three systems, a release that attaches the binaries with checksums, pushes the image to GHCR and
packages the chart, and a chart end-to-end job. The workflows themselves run only on GitHub, so these tests check them
locally; actionlint, when installed, is a second check.

Run: python3 -m unittest discover -s tests/packaging -v
"""
import re  # patterns in steps
import unittest  # the test framework

from pkg_support import ROOT, WORKFLOWS, need_yaml, run, tool, yaml

NAMES = ("ci", "desktop", "release", "chart-e2e", "look")


def load(name: str) -> dict:
    """A workflow as a dict; YAML 1.1 reads the key `on` as the boolean True, so it is put back under "on" """
    doc = yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8"))
    if True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc


def steps(job: dict) -> list:
    return job.get("steps", [])


def uses(doc: dict) -> list:
    """Every `uses:` of a workflow, jobs and steps alike"""
    found = []
    for job in doc["jobs"].values():
        if "uses" in job:
            found.append(job["uses"])
        found += [s["uses"] for s in steps(job) if "uses" in s]
    return found


def scripts(doc: dict) -> list:
    return [s["run"] for job in doc["jobs"].values() for s in steps(job) if "run" in s]


def claimed_pythons() -> list:
    """The Python versions pyproject.toml's classifiers name, oldest first (read as text: tomllib is not in 3.10)"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return sorted(re.findall(r'"Programming Language :: Python :: (3\.\d+)"', text), key=lambda v: int(v.split(".")[1]))


class WorkflowFilesTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)

    def test_every_workflow_exists_and_parses(self):
        for name in NAMES:
            doc = load(name)
            self.assertIn("jobs", doc, name)
            self.assertIn("on", doc, name)

    def test_the_original_ci_jobs_are_still_there_and_the_packaging_jobs_were_added(self):
        jobs = load("ci")["jobs"]
        for name in ("lint-and-cli-tests", "selftest", "packaging", "package-install", "app-image"):
            self.assertIn(name, jobs)

    def test_every_job_has_a_runner_and_a_time_limit(self):
        for name in NAMES:
            for key, job in load(name)["jobs"].items():
                if "uses" in job:  # a call of another workflow
                    continue
                self.assertIn("runs-on", job, f"{name}/{key}")
                self.assertIn("timeout-minutes", job, f"{name}/{key}")

    def test_every_action_is_pinned_to_a_release_never_a_branch(self):
        for name in NAMES:
            for ref in uses(load(name)):
                if ref.startswith("./"):
                    self.assertTrue((ROOT / ref[2:]).is_file(), f"{name}: {ref} does not exist")
                    continue
                self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$", f"{name}: {ref} must be pinned to a version or a commit")

    def test_the_actions_come_from_the_same_few_owners_the_sibling_project_uses(self):
        owners = {ref.split("/")[0] for name in NAMES for ref in uses(load(name)) if not ref.startswith("./")}
        self.assertLessEqual(owners, {"actions", "docker", "azure", "softprops"})

    def test_needs_name_jobs_that_exist(self):
        for name in NAMES:
            jobs = load(name)["jobs"]
            for key, job in jobs.items():
                needs = job.get("needs", [])
                for n in [needs] if isinstance(needs, str) else needs:
                    self.assertIn(n, jobs, f"{name}/{key} needs {n}")

    def test_the_called_workflows_can_be_called(self):
        for caller in NAMES:
            for job in load(caller)["jobs"].values():
                ref = job.get("uses", "")
                if ref.startswith("./.github/workflows/"):
                    callee = load(ref.split("/")[-1].removesuffix(".yml"))
                    self.assertIn("workflow_call", callee["on"], f"{caller} calls {ref}, which has no workflow_call trigger")

    def test_the_token_has_the_least_it_needs(self):
        for name in NAMES:
            doc = load(name)
            self.assertEqual(doc.get("permissions"), {"contents": "read"}, name)  # the default for every job
        release = load("release")["jobs"]["release"]["permissions"]
        self.assertEqual(release, {"contents": "write", "packages": "write", "id-token": "write", "attestations": "write"})

    def test_no_untrusted_text_is_interpolated_into_a_script(self):
        # github.head_ref, the pull request's title or body, a branch name or a commit message can hold shell syntax
        danger = re.compile(r"\$\{\{\s*(github\.(head_ref|event\.(pull_request|issue|comment|head_commit|review)\b))")
        for name in NAMES:
            for script in scripts(load(name)):
                self.assertIsNone(danger.search(script), f"{name}: {script[:80]}")

    def test_no_workflow_runs_code_from_a_pull_request_with_secrets(self):
        for name in NAMES:
            on = load(name)["on"]
            self.assertNotIn("pull_request_target", on, name)
            self.assertNotIn("secrets", " ".join(scripts(load(name))).replace("secrets.GITHUB_TOKEN", ""), name)  # only the built-in token

    def test_tools_that_are_downloaded_are_checked_against_a_checksum(self):
        for name in NAMES:
            for script in scripts(load(name)):
                for download in re.findall(r"curl [^\n]*-o (\S+) (https?://\S+)", script):
                    self.assertRegex(script, rf"sha256sum -c", f"{name}: {download[1]} is downloaded without a checksum")
                for checksum in re.findall(r'echo "([0-9a-f]+)  /tmp/', script):
                    self.assertEqual(len(checksum), 64, checksum)

    def test_the_pinned_tools_are_the_ones_the_tests_were_run_with(self):
        text = (WORKFLOWS / "chart-e2e.yml").read_text(encoding="utf-8")
        self.assertIn("kind/releases/download/v0.29.0/kind-linux-amd64", text)
        self.assertIn("c72eda46430f065fb45c5f70e7c957cc9209402ef309294821978677c8fb3284", text)


class DesktopTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)
        self.doc = load("desktop")
        self.job = self.doc["jobs"]["build"]

    def test_it_builds_on_windows_macos_and_linux_without_stopping_at_the_first_failure(self):
        matrix = self.job["strategy"]["matrix"]["include"]
        systems = {m["os"].split("-")[0] for m in matrix}
        self.assertEqual(systems, {"windows", "macos", "ubuntu"})
        self.assertIn("windows-latest", [m["os"] for m in matrix])
        self.assertIn("macos-latest", [m["os"] for m in matrix])
        self.assertIs(self.job["strategy"]["fail-fast"], False)
        # Linux on a pinned older runner: the file runs on the glibc it was built with and on newer ones
        self.assertTrue([m for m in matrix if m["os"].startswith("ubuntu-22")])

    def test_it_runs_the_apps_own_build_which_checks_the_result(self):
        commands = " ".join(scripts(self.doc))
        self.assertIn("python apps/desktop/build.py", commands)
        self.assertIn("-r apps/desktop/requirements-build.txt", commands)
        self.assertTrue((ROOT / "apps" / "desktop" / "build.py").is_file())

    def test_it_keeps_the_files_build_py_names(self):
        upload = [s for s in steps(self.job) if s.get("uses", "").startswith("actions/upload-artifact")][0]
        self.assertEqual(upload["with"]["path"], "dist/Offerowl-*")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        self.assertIn("runner.os", upload["with"]["name"])  # one artifact name per system
        self.assertIn("runner.arch", upload["with"]["name"])  # and per architecture (two macOS builds)
        build_py = (ROOT / "apps" / "desktop" / "build.py").read_text(encoding="utf-8")
        self.assertIn('f"Offerowl-{system}-{machine}', build_py)

    def test_it_can_be_called_by_the_release_and_started_by_hand(self):
        self.assertIn("workflow_call", self.doc["on"])
        self.assertIn("workflow_dispatch", self.doc["on"])


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)
        self.doc = load("release")
        self.release = self.doc["jobs"]["release"]
        self.text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    def test_a_version_tag_starts_it(self):
        self.assertEqual(self.doc["on"], {"push": {"tags": ["v*.*.*"]}})

    def test_nothing_is_published_before_the_checks_the_cluster_test_and_the_desktop_builds_pass(self):
        self.assertEqual(sorted(self.release["needs"]), ["chart", "desktop", "verify"])
        self.assertEqual(self.doc["jobs"]["chart"]["uses"], "./.github/workflows/chart-e2e.yml")
        self.assertEqual(self.doc["jobs"]["desktop"]["uses"], "./.github/workflows/desktop.yml")

    def test_the_tag_must_name_the_version_the_package_carries(self):
        verify = " ".join(scripts({"jobs": {"verify": self.doc["jobs"]["verify"]}}))
        self.assertIn("deploy/python/offerowl/__init__.py", verify)
        self.assertIn("the tag says", verify)

    def test_the_image_is_pushed_to_ghcr_for_two_architectures(self):
        build = [s for s in steps(self.release) if s.get("uses", "").startswith("docker/build-push-action")][0]
        self.assertIs(build["with"]["push"], True)
        self.assertEqual(build["with"]["file"], "deploy/docker/Dockerfile")
        self.assertEqual(build["with"]["platforms"], "linux/amd64,linux/arm64")
        meta = [s for s in steps(self.release) if s.get("uses", "").startswith("docker/metadata-action")][0]
        self.assertTrue(meta["with"]["images"].startswith("ghcr.io/"))
        self.assertTrue(meta["with"]["images"].endswith("/offerowl-app"))
        login = [s for s in steps(self.release) if s.get("uses", "").startswith("docker/login-action")][0]
        self.assertEqual(login["with"]["registry"], "ghcr.io")
        self.assertIn("docker/setup-qemu-action", " ".join(uses(self.doc)))  # arm64 is built under emulation

    def test_latest_goes_only_to_a_release_that_is_not_a_prerelease(self):
        self.assertIn("type=raw,value=latest,enable=${{ steps.v.outputs.prerelease == 'false' }}", self.text)
        self.assertIn("prerelease: ${{ steps.v.outputs.prerelease == 'true' }}", self.text)

    def test_the_chart_is_packaged_under_the_release_version_and_pushed_as_oci(self):
        script = " ".join(scripts(self.doc))
        self.assertIn('helm package deploy/helm/offerowl --version "${VERSION}" --app-version "${VERSION}"', script)
        self.assertIn('helm push "dist/offerowl-${VERSION}.tgz" "oci://ghcr.io/${OWNER}/charts"', script)
        self.assertIn("helm lint deploy/helm/offerowl", script)
        self.assertIn('repository: ghcr.io/${OWNER}/offerowl-app', script)  # the packaged chart names the published image

    def test_the_python_package_is_built_and_attached(self):
        self.assertIn("python -m build", " ".join(scripts(self.doc)))
        files = [s for s in steps(self.release) if s.get("uses", "").startswith("softprops/action-gh-release")][0]["with"]["files"]
        self.assertIn("-py3-none-any.whl", files)
        self.assertIn(".tar.gz", files)

    def test_the_binaries_and_the_checksums_are_attached_and_signed(self):
        files = [s for s in steps(self.release) if s.get("uses", "").startswith("softprops/action-gh-release")][0]["with"]["files"]
        for want in ("dist/app/Offerowl-*", "dist/SHA256SUMS", "offerowl-${{ steps.v.outputs.version }}.tgz"):
            self.assertIn(want, files)
        download = [s for s in steps(self.release) if s.get("uses", "").startswith("actions/download-artifact")][0]["with"]
        self.assertEqual(download["pattern"], "Offerowl-*")  # what desktop.yml uploads
        self.assertIn("sha256sum", " ".join(scripts(self.doc)))
        attest = [s for s in steps(self.release) if s.get("uses", "").startswith("actions/attest-build-provenance")]
        self.assertEqual(len(attest), 2)  # the image, and the files

    def test_the_token_reaches_the_registry_only_through_the_environment(self):
        for step in steps(self.release):
            if "run" in step:
                self.assertNotIn("secrets.", step["run"], "a secret is passed through env:, never written into the script")


class ChartE2eTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)
        self.doc = load("chart-e2e")

    def test_it_builds_the_image_installs_the_chart_on_kind_and_runs_the_script(self):
        job = self.doc["jobs"]["kind"]
        build = [s for s in steps(job) if s.get("uses", "").startswith("docker/build-push-action")][0]["with"]
        self.assertIs(build["load"], True)
        self.assertEqual(build["file"], "deploy/docker/Dockerfile")
        self.assertIn("tests/packaging/chart_e2e.sh offerowl-app:e2e", " ".join(scripts(self.doc)))
        self.assertEqual(build["tags"], "offerowl-app:e2e")
        self.assertTrue((ROOT / "tests" / "packaging" / "chart_e2e.sh").is_file())

    def test_it_runs_on_chart_and_code_changes_by_hand_and_before_a_release(self):
        on = self.doc["on"]
        self.assertIn("workflow_dispatch", on)
        self.assertIn("workflow_call", on)
        paths = on["push"]["paths"]
        for path in ("deploy/**", "apps/**", "src/**", "tests/packaging/chart_e2e.sh"):
            self.assertIn(path, paths)


class CiTest(unittest.TestCase):
    def setUp(self):
        need_yaml(self)
        self.doc = load("ci")

    def test_the_packaging_jobs_run_the_tests_of_this_folder_with_every_tool_required(self):
        job = self.doc["jobs"]["packaging"]
        self.assertEqual(job["env"]["OFFEROWL_REQUIRE_TOOLS"], "1")
        self.assertEqual(job["env"]["OFFEROWL_REQUIRE_HOOKS"], "1")
        self.assertEqual(load("release")["jobs"]["verify"]["env"]["OFFEROWL_REQUIRE_HOOKS"], "1")
        text = " ".join(scripts({"jobs": {"packaging": job}}))
        for want in ("python3 -m unittest discover -s tests/packaging -v", "helm lint deploy/helm/offerowl", "actionlint",
                     "docker compose -f deploy/docker/compose.yaml config --quiet", "kubeconform"):
            self.assertIn(want, text)

    def test_pip_install_is_tried_on_the_three_systems_with_the_oldest_and_the_newest_python(self):
        job = self.doc["jobs"]["package-install"]
        self.assertEqual(job["strategy"]["matrix"]["os"], ["ubuntu-24.04", "macos-latest", "windows-latest"])
        claimed = claimed_pythons()
        self.assertEqual(job["strategy"]["matrix"]["python"], [claimed[0], claimed[-1]])  # the oldest and the newest it claims
        python = [s for s in steps(job) if s.get("uses", "").startswith("actions/setup-python")][0]["with"]["python-version"]
        self.assertEqual(python, "${{ matrix.python }}")
        self.assertIn("python -m venv", " ".join(scripts({"jobs": {"j": job}})))

    def test_the_quick_tests_run_on_every_python_the_package_claims(self):
        claimed = claimed_pythons()
        self.assertEqual(self.doc["jobs"]["lint-and-cli-tests"]["strategy"]["matrix"]["python"], claimed)  # none left untested
        lower = re.search(r'requires-python = ">=(3\.\d+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
        self.assertEqual(lower, claimed[0])  # the oldest one named is the oldest pip installs it on
        self.assertEqual(["3.10", "3.11", "3.12", "3.13", "3.14", "3.15"], claimed)  # each one between, none skipped

    def test_the_app_image_is_built_and_started_the_way_compose_starts_it(self):
        job = self.doc["jobs"]["app-image"]
        self.assertIn("tests/packaging/image_smoke.sh offerowl-app:ci --selftest", " ".join(scripts({"jobs": {"j": job}})))
        self.assertTrue((ROOT / "tests" / "packaging" / "image_smoke.sh").is_file())
        self.assertIn("tests/packaging/offline_e2e.sh offerowl-app:ci", (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))  # and with no network at all
        self.assertTrue((ROOT / "tests" / "packaging" / "offline_e2e.sh").is_file())


class LookTest(unittest.TestCase):
    """The look at the panel in Safari: by hand or from its own branch only, on a macOS runner, its pictures kept."""

    def setUp(self):
        need_yaml(self)
        self.doc = load("look")

    def test_it_is_started_by_hand_or_by_its_own_branch_never_by_main_or_a_tag(self):
        on = self.doc["on"]
        self.assertIn("workflow_dispatch", on)
        self.assertEqual(on.get("push"), {"branches": ["look-safari"]})

    def test_it_drives_safari_on_macos_and_keeps_what_it_saw(self):
        job = self.doc["jobs"]["safari"]
        self.assertTrue(job["runs-on"].startswith("macos"))
        text = " ".join(scripts(self.doc))
        self.assertIn("safaridriver --enable", text)
        self.assertIn("python .github/look/safari.py look-safari", text)
        self.assertTrue(any(s.get("uses", "").startswith("actions/upload-artifact@") for s in steps(job)))
        self.assertTrue((ROOT / ".github" / "look" / "safari.py").is_file())


class ActionlintTest(unittest.TestCase):
    def test_actionlint_finds_nothing_in_any_workflow(self):
        actionlint = tool(self, "actionlint")
        files = sorted(str(p.relative_to(ROOT)) for p in WORKFLOWS.glob("*.yml"))  # named, because with no names it looks for a git project
        self.assertEqual(len(files), len(NAMES))
        r = run([actionlint, *files], cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
