"""The installers a release carries (scripts/install.sh, install.ps1, installers.sh): each copy installs its own release,
and the Linux one installs the app for this user, linked by name, with no network (curl is a stand-in that serves a made-up
release) and nothing opened (OFFEROWL_INSTALL_ONLY).

    python3 -m unittest tests/packaging/test_installers.py -v
"""
import io  # the made-up app's archive
import os  # the environment of the install
import pathlib  # paths
import shutil  # clean up
import subprocess  # the scripts as people run them
import tarfile  # the Linux app's archive
import tempfile  # a home per test
import unittest  # the runner

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
SCRIPTS = ROOT / "scripts"

FAKE_CURL = """#!/bin/sh
# curl for the test: the latest release's redirect, or the made-up archive, never the network
out=""; url=""; effective=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift ;;
    -w) effective=1; shift ;;
    -*) ;;
    *) url=$1 ;;
  esac
  shift
done
echo "$url" >> "$CALLS"
if [ "$effective" = 1 ]; then printf '%s' "https://github.com/kanggu12/offerowl/releases/tag/v9.9.9"; exit 0; fi
case "$url" in
  */offerowl-9.9.9-linux-x64.tar.gz) cp "$ARCHIVE" "$out" ;;
  *) exit 22 ;;
esac
"""


@unittest.skipUnless(os.name == "posix" and shutil.which("sh") and shutil.which("tar"), "a POSIX shell and tar")
class InstallersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="offerowl-install-"))  # never the person's home
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_each_copy_installs_its_own_release(self):
        """installers.sh writes the three installers with the release in their first lines and their usage lines."""
        out = self.tmp / "out"
        subprocess.run(["sh", str(SCRIPTS / "installers.sh"), "v1.2.3", str(out)], check=True, capture_output=True)
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(["offerowl-1.2.3-linux-installer.sh", "offerowl-1.2.3-macos-installer.sh", "offerowl-1.2.3-windows-installer.ps1"], names)
        sh = (out / "offerowl-1.2.3-linux-installer.sh").read_text(encoding="utf-8")
        self.assertIn('\nrelease="v1.2.3"\n', sh)
        self.assertIn("/releases/download/v1.2.3/offerowl-1.2.3-linux-installer.sh | sh", sh)
        ps = (out / "offerowl-1.2.3-windows-installer.ps1").read_text(encoding="utf-8")
        self.assertIn("\n  $release = 'v1.2.3'\n", ps)
        self.assertIn("/releases/download/v1.2.3/offerowl-1.2.3-windows-installer.ps1 | iex", ps)
        bad = subprocess.run(["sh", str(SCRIPTS / "installers.sh"), "v1.2.3'; rm -rf /", str(out)], capture_output=True)
        self.assertNotEqual(0, bad.returncode)  # a tag that would end up inside the scripts' quotes is refused

    def test_the_scripts_are_ascii(self):
        """Windows PowerShell 5.1 reads a .ps1 without a byte order mark in the system's code page: anything but ASCII
        would change on the way."""
        for name in ("install.ps1", "install.sh", "installers.sh"):
            (SCRIPTS / name).read_bytes().decode("ascii")  # raises on any other byte

    def test_the_linux_installer_installs_the_app_for_this_user(self):
        """The latest release (no version written in), its one-file app as ~/.local/bin/offerowl, which runs, and nothing
        in the data folder."""
        home, tools = self.tmp / "home", self.tmp / "tools"
        tools.mkdir()
        (tools / "curl").write_text(FAKE_CURL, encoding="utf-8")
        (tools / "curl").chmod(0o755)
        app = b"#!/bin/sh\necho offerowl 9.9.9\n"  # the one-file app, made up
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("offerowl")
            info.size, info.mode = len(app), 0o755
            tar.addfile(info, io.BytesIO(app))
        (self.tmp / "app.tar.gz").write_bytes(buf.getvalue())
        env = {"PATH": f"{tools}:/usr/bin:/bin", "HOME": str(home), "OFFEROWL_INSTALL_ONLY": "1",
               "ARCHIVE": str(self.tmp / "app.tar.gz"), "CALLS": str(self.tmp / "calls.txt")}
        if os.uname().sysname != "Linux" or os.uname().machine not in ("x86_64", "amd64"):
            self.skipTest("the Linux x86-64 path")
        r = subprocess.run(["sh", str(SCRIPTS / "install.sh")], env=env, capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        app_file = home / ".local" / "bin" / "offerowl"
        self.assertTrue(app_file.is_file() and os.access(app_file, os.X_OK))
        self.assertFalse((home / ".local" / "share" / "offerowl").exists())  # the data folder is the person's files alone
        self.assertEqual("offerowl 9.9.9", subprocess.run([str(app_file)], capture_output=True, text=True).stdout.strip())
        calls = (self.tmp / "calls.txt").read_text(encoding="utf-8").split()
        self.assertEqual(["https://github.com/kanggu12/offerowl/releases/latest",
                          "https://github.com/kanggu12/offerowl/releases/download/v9.9.9/offerowl-9.9.9-linux-x64.tar.gz"], calls)
        self.assertIn("add", r.stdout)  # ~/.local/bin is not on this PATH: it says so


if __name__ == "__main__":
    unittest.main()
