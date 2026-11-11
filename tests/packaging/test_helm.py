"""Tests of the Helm chart (deploy/helm/offerowl): it lints, it renders for each choice of values, the pod is hardened and
its probes send the Host header the panel accepts, the AI values reach the container, and settings that cannot work are
refused with a sentence that says what to change. Helm renders locally; no cluster is needed here
(tests/packaging/chart_e2e.sh installs the chart on a throwaway cluster).

Run: python3 -m unittest discover -s tests/packaging -v
"""
import json  # helm's JSON values
import pathlib  # paths
import shutil  # find tools
import unittest  # the test framework

from pkg_support import CHART, ROOT, clean_env, need_yaml, package_version, run, tmpdir, tool, yaml


class ChartTest(unittest.TestCase):
    helm = ""

    @classmethod
    def setUpClass(cls):
        cls.helm = shutil.which("helm") or ""

    def setUp(self):
        need_yaml(self)
        if not self.helm:
            tool(self, "helm")  # skips, or fails under OFFEROWL_REQUIRE_TOOLS=1

    def render(self, *sets: str, values: dict | None = None, name: str = "offerowl", check: bool = True):
        """helm template with --set arguments; returns the parsed objects as {kind: [object, ...]}"""
        cmd = [self.helm, "template", name, str(CHART), "--namespace", "ns"]
        for item in sets:
            cmd += ["--set", item]
        if values is not None:
            f = tmpdir(self) / "values.json"
            f.write_text(json.dumps(values), encoding="utf-8")
            cmd += ["-f", str(f)]
        r = run(cmd)
        if not check:
            return r
        self.assertEqual(r.returncode, 0, r.stderr)
        out: dict = {}
        for doc in yaml.safe_load_all(r.stdout):
            if doc:
                out.setdefault(doc["kind"], []).append(doc)
        return out

    def container(self, objs: dict) -> dict:
        return objs["Deployment"][0]["spec"]["template"]["spec"]["containers"][0]

    def env(self, objs: dict) -> dict:
        return {e["name"]: e for e in self.container(objs)["env"]}

    # --- lint and defaults

    def test_helm_lint_is_clean(self):
        r = run([self.helm, "lint", "--strict", str(CHART)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_default_render_makes_a_deployment_a_service_a_claim_a_policy_and_the_test_pod_and_no_ingress(self):
        objs = self.render()
        self.assertEqual(sorted(objs), ["Deployment", "NetworkPolicy", "PersistentVolumeClaim", "Pod", "Service"])
        for kind in objs:
            self.assertEqual(len(objs[kind]), 1, kind)
        self.assertEqual(objs["Pod"][0]["metadata"]["annotations"]["helm.sh/hook"], "test")  # the only Pod is the one helm test runs

    def test_the_chart_names_the_version_of_the_package_and_the_image_follows_it(self):
        objs = self.render()
        self.assertEqual(self.container(objs)["image"], f"offerowl-app:{package_version()}")
        self.assertEqual(objs["Deployment"][0]["metadata"]["labels"]["app.kubernetes.io/version"], package_version())

    def test_the_image_and_its_tag_can_be_named(self):
        objs = self.render("image.repository=ghcr.io/example/offerowl-app", "image.tag=9.9.9")
        self.assertEqual(self.container(objs)["image"], "ghcr.io/example/offerowl-app:9.9.9")

    # --- the pod

    def test_the_pod_is_hardened(self):
        pod = self.render()["Deployment"][0]["spec"]["template"]["spec"]
        self.assertEqual(pod["securityContext"]["runAsNonRoot"], True)
        self.assertEqual(pod["securityContext"]["runAsUser"], 10001)  # the image's own user
        self.assertEqual(pod["securityContext"]["seccompProfile"], {"type": "RuntimeDefault"})
        self.assertIs(pod["automountServiceAccountToken"], False)
        c = pod["containers"][0]["securityContext"]
        self.assertIs(c["readOnlyRootFilesystem"], True)
        self.assertIs(c["allowPrivilegeEscalation"], False)
        self.assertEqual(c["capabilities"], {"drop": ["ALL"]})
        self.assertNotIn("privileged", c)
        self.assertNotIn("hostNetwork", pod)

    def test_one_pod_with_the_claim_replaced_in_order(self):
        d = self.render()["Deployment"][0]["spec"]
        self.assertEqual(d["replicas"], 1)
        self.assertEqual(d["strategy"], {"type": "Recreate"})  # a ReadWriteOnce claim cannot be mounted twice

    def test_the_probes_send_the_host_header_the_panel_accepts(self):
        c = self.container(self.render())
        for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
            get = c[probe]["httpGet"]
            self.assertEqual(get["path"], "/health", probe)
            self.assertEqual(get["httpHeaders"], [{"name": "Host", "value": "127.0.0.1:8797"}], probe)
        self.assertEqual(c["ports"][0], {"name": "http", "containerPort": 8797, "protocol": "TCP"})

    def test_the_panels_port_follows_the_value_everywhere(self):
        objs = self.render("service.panelPort=18797")
        c = self.container(objs)
        self.assertEqual(self.env(objs)["OFFEROWL_PANEL_PORT"]["value"], "18797")
        self.assertEqual(c["ports"][0]["containerPort"], 18797)
        self.assertEqual(c["startupProbe"]["httpGet"]["httpHeaders"][0]["value"], "127.0.0.1:18797")
        self.assertEqual([p["port"] for p in objs["Service"][0]["spec"]["ports"]], [18797])  # the panel serves the interview kit too
        self.assertEqual(len(c["ports"]), 1)  # no second port on the pod

    def test_the_data_folder_is_the_claim_and_the_scratch_folders_are_in_memory(self):
        pod = self.render()["Deployment"][0]["spec"]["template"]["spec"]
        mounts = {m["mountPath"]: m["name"] for m in pod["containers"][0]["volumeMounts"]}
        self.assertEqual(mounts, {"/tmp": "tmp", "/work/output": "output", "/data": "data"})
        volumes = {v["name"]: v for v in pod["volumes"]}
        self.assertEqual(volumes["data"]["persistentVolumeClaim"]["claimName"], "offerowl-data")
        self.assertEqual(volumes["tmp"]["emptyDir"]["medium"], "Memory")
        self.assertEqual(volumes["output"]["emptyDir"]["medium"], "Memory")

    def test_the_environment_fixes_what_the_container_needs(self):
        env = self.env(self.render())
        self.assertEqual(env["OFFEROWL_DATA_DIR"]["value"], "/data")
        for name in ("OFFEROWL_INTERVIEW_HOST", "OFFEROWL_INTERVIEW_PORT"):  # the interview kit is served by the panel: no port of its own
            self.assertNotIn(name, env)
        self.assertEqual(env["OFFEROWL_LLM"]["value"], "none")
        self.assertEqual(env["TZ"]["value"], "UTC")
        for name in ("OFFEROWL_LLM_URL", "OFFEROWL_LLM_MODEL", "OFFEROWL_LLM_KEY", "OFFEROWL_ALLOWED_HOSTS", "OFFEROWL_LANG"):
            self.assertNotIn(name, env)

    # --- storage

    def test_the_claim_is_kept_on_uninstall(self):
        pvc = self.render()["PersistentVolumeClaim"][0]
        self.assertEqual(pvc["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
        self.assertEqual(pvc["spec"]["resources"]["requests"]["storage"], "5Gi")
        self.assertEqual(pvc["spec"]["accessModes"], ["ReadWriteOnce"])

    def test_without_persistence_there_is_no_claim_and_the_data_is_an_empty_dir(self):
        objs = self.render("persistence.enabled=false")
        self.assertNotIn("PersistentVolumeClaim", objs)
        volumes = {v["name"]: v for v in objs["Deployment"][0]["spec"]["template"]["spec"]["volumes"]}
        self.assertIn("emptyDir", volumes["data"])

    def test_an_existing_claim_is_used_and_none_is_made(self):
        objs = self.render("persistence.existingClaim=mine")
        self.assertNotIn("PersistentVolumeClaim", objs)
        volumes = {v["name"]: v for v in objs["Deployment"][0]["spec"]["template"]["spec"]["volumes"]}
        self.assertEqual(volumes["data"]["persistentVolumeClaim"]["claimName"], "mine")

    def test_the_storage_class_is_left_out_unless_named(self):
        self.assertNotIn("storageClassName", self.render()["PersistentVolumeClaim"][0]["spec"])
        self.assertEqual(self.render("persistence.storageClass=fast")["PersistentVolumeClaim"][0]["spec"]["storageClassName"], "fast")
        self.assertEqual(self.render("persistence.storageClass=-")["PersistentVolumeClaim"][0]["spec"]["storageClassName"], "")

    # --- the AI backend

    def test_a_local_model_server_reaches_the_container(self):
        objs = self.render("ai.backend=openai-compat", "ai.url=http://ollama.models.svc:11434", "ai.model=my-model")
        env = self.env(objs)
        self.assertEqual(env["OFFEROWL_LLM"]["value"], "openai-compat")
        self.assertEqual(env["OFFEROWL_LLM_URL"]["value"], "http://ollama.models.svc:11434")
        self.assertEqual(env["OFFEROWL_LLM_MODEL"]["value"], "my-model")
        self.assertNotIn("OFFEROWL_LLM_KEY", env)

    def test_the_key_comes_from_a_secret_and_is_never_a_value(self):
        objs = self.render("ai.backend=openai-compat", "ai.url=http://x", "ai.existingSecret=model-key", "ai.secretKey=token")
        key = self.env(objs)["OFFEROWL_LLM_KEY"]
        self.assertEqual(key["valueFrom"]["secretKeyRef"], {"name": "model-key", "key": "token"})
        self.assertNotIn("value", key)

    def test_no_secret_or_config_map_is_made_by_the_chart(self):
        objs = self.render("ai.backend=openai-compat", "ai.url=http://x", "ai.existingSecret=model-key")
        self.assertNotIn("Secret", objs)
        self.assertNotIn("ConfigMap", objs)

    # --- ingress, policy

    def test_the_ingress_is_off_by_default_and_names_the_hosts_when_on(self):
        self.assertNotIn("Ingress", self.render())
        objs = self.render(values={"ingress": {"enabled": True, "className": "nginx", "hosts": [
            {"host": "a.example.invalid", "paths": [{"path": "/", "pathType": "Prefix"}]},
            {"host": "b.example.invalid", "paths": [{"path": "/", "pathType": "Prefix"}]}]}})
        ingress = objs["Ingress"][0]["spec"]
        self.assertEqual([r["host"] for r in ingress["rules"]], ["a.example.invalid", "b.example.invalid"])
        self.assertEqual(ingress["rules"][0]["http"]["paths"][0]["backend"]["service"], {"name": "offerowl", "port": {"name": "http"}})
        self.assertEqual(ingress["ingressClassName"], "nginx")
        # the panel refuses a Host header it does not know, so it is told the Ingress' names
        self.assertEqual(self.env(objs)["OFFEROWL_ALLOWED_HOSTS"]["value"], "a.example.invalid,b.example.invalid")

    def test_the_service_is_cluster_internal(self):
        svc = self.render()["Service"][0]["spec"]
        self.assertEqual(svc["type"], "ClusterIP")
        self.assertEqual([(p["name"], p["port"]) for p in svc["ports"]], [("http", 8797)])  # the panel, which serves the interview kit too

    def test_the_policy_lets_no_pod_in_except_the_charts_own_test_pod_and_what_is_listed(self):
        policy = self.render()["NetworkPolicy"][0]["spec"]
        self.assertEqual(policy["policyTypes"], ["Ingress"])
        sources = policy["ingress"][0]["from"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["podSelector"]["matchLabels"]["app.kubernetes.io/component"], "test")
        more = self.render(values={"networkPolicy": {"allowFrom": [{"namespaceSelector": {"matchLabels": {"x": "y"}}}]}})
        self.assertEqual(len(more["NetworkPolicy"][0]["spec"]["ingress"][0]["from"]), 2)
        self.assertNotIn("NetworkPolicy", self.render("networkPolicy.enabled=false"))

    def test_the_test_pod_sends_the_host_header_and_is_hardened_too(self):
        r = run([self.helm, "template", "offerowl", str(CHART), "--show-only", "templates/tests/test-connection.yaml"])
        pod = yaml.safe_load(r.stdout)
        self.assertEqual(pod["metadata"]["annotations"]["helm.sh/hook"], "test")
        self.assertEqual(pod["metadata"]["labels"]["app.kubernetes.io/component"], "test")
        script = pod["spec"]["containers"][0]["args"][0]
        self.assertIn('"Host": "127.0.0.1:8797"', script)
        self.assertIn("http://offerowl:8797/health", script)
        self.assertIs(pod["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"], True)
        self.assertEqual(pod["spec"]["securityContext"]["runAsNonRoot"], True)

    # --- names, extra settings

    def test_names_follow_the_release_and_can_be_replaced(self):
        self.assertEqual(self.render(name="work")["Deployment"][0]["metadata"]["name"], "work-offerowl")
        self.assertEqual(self.render(name="offerowl-prod")["Deployment"][0]["metadata"]["name"], "offerowl-prod")
        self.assertEqual(self.render("fullnameOverride=mine")["Service"][0]["metadata"]["name"], "mine")

    def test_extra_environment_is_appended_and_the_language_is_passed(self):
        objs = self.render("language=ko", values={"extraEnv": [{"name": "OFFEROWL_LLM_REASONING", "value": "none"}]})
        env = self.env(objs)
        self.assertEqual(env["OFFEROWL_LANG"]["value"], "ko")
        self.assertEqual(env["OFFEROWL_LLM_REASONING"]["value"], "none")

    # --- settings that cannot work are refused, with the sentence that says what to change

    def refused(self, *sets: str, values: dict | None = None) -> str:
        r = self.render(*sets, values=values, check=False)
        self.assertNotEqual(r.returncode, 0, "the chart accepted settings that cannot work")
        return r.stderr

    def test_a_backend_that_is_not_in_the_image_is_refused(self):
        for backend in ("claude-code", "codex", "gpt"):
            self.assertIn("ai.backend must be none or openai-compat", self.refused(f"ai.backend={backend}"))
        self.assertIn("stay signed in", self.refused("ai.backend=claude-code"))

    def test_a_local_server_needs_an_address(self):
        self.assertIn("ai.url", self.refused("ai.backend=openai-compat"))

    def test_a_secret_needs_its_key_name(self):
        self.assertIn("ai.secretKey", self.refused("ai.backend=openai-compat", "ai.url=http://x", "ai.existingSecret=s", "ai.secretKey="))

    def test_ports_must_suit_a_pod_that_is_not_root_and_differ(self):
        self.assertIn("between 1024 and 65535", self.refused("service.panelPort=80"))
        self.assertIn("between 1024 and 65535", self.refused("service.panelPort=70000"))

    def test_an_ingress_needs_a_host(self):
        self.assertIn("ingress.hosts", self.refused(values={"ingress": {"enabled": True, "hosts": []}}))

    def test_extra_environment_may_not_replace_what_the_chart_sets(self):
        for name in ("OFFEROWL_PANEL_PORT", "OFFEROWL_LLM_KEY", "OFFEROWL_DATA_DIR", "OFFEROWL_ALLOWED_HOSTS", "TZ", "HOME"):
            self.assertIn(f"extraEnv may not set {name}", self.refused(values={"extraEnv": [{"name": name, "value": "x"}]}), name)

    # --- manifests and packaging

    def test_the_manifests_are_valid_kubernetes(self):
        kubeconform = tool(self, "kubeconform")
        for sets in ((), ("ai.backend=openai-compat", "ai.url=http://x", "ai.existingSecret=s"), ("persistence.enabled=false",)):
            cmd = [self.helm, "template", "offerowl", str(CHART)]
            for item in sets:
                cmd += ["--set", item]
            manifest = run(cmd).stdout
            r = run([kubeconform, "-strict", "-ignore-missing-schemas", "-summary", "-"], input=manifest)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ingress = run([self.helm, "template", "offerowl", str(CHART), "--set", "ingress.enabled=true"]).stdout
        self.assertEqual(run([kubeconform, "-strict", "-ignore-missing-schemas", "-"], input=ingress).returncode, 0)

    def test_the_chart_packages_under_a_release_version(self):
        out = tmpdir(self)
        r = run([self.helm, "package", str(CHART), "--version", "9.8.7", "--app-version", "9.8.7", "--destination", str(out)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([p.name for p in out.iterdir()], ["offerowl-9.8.7.tgz"])

    def test_the_release_workflow_can_point_the_chart_at_the_registry(self):
        # release.yml rewrites exactly one line of values.yaml with sed and checks that it did
        values = (CHART / "values.yaml").read_text(encoding="utf-8")
        self.assertEqual(values.count("\n  repository: offerowl-app\n"), 1)
        self.assertEqual(sum(1 for line in values.splitlines() if line.startswith("  repository:")), 1)


if __name__ == "__main__":
    unittest.main()
