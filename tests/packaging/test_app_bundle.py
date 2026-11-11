"""The macOS bundle of the desktop app (apps/desktop/build.py): Offerowl.app in a zip that keeps the program's execute bit, with
the description Finder reads. It is written with the standard library, so it is checked here on any system; the program in it is
the file the build has already started with --check."""
import importlib.util  # the build script, by its file
import pathlib  # paths
import plistlib  # the bundle's description
import stat  # the modes in the zip
import tempfile  # a place for the bundle
import unittest  # the runner
import zipfile  # the bundle's zip

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repository
SPEC = importlib.util.spec_from_file_location("offerowl_app_build", ROOT / "apps" / "desktop" / "build.py")  # not on the import path
BUILD = importlib.util.module_from_spec(SPEC)  # the module
SPEC.loader.exec_module(BUILD)  # read once


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # removed after the test
        self.addCleanup(self.tmp.cleanup)  # even after a failure
        self.dir = pathlib.Path(self.tmp.name)  # the folder
        exe = self.dir / "Offerowl"  # a stand-in for the built program
        exe.write_bytes(b"#!/bin/sh\n")  # its content does not matter here
        exe.chmod(0o755)  # as PyInstaller leaves it
        self.named = BUILD.mac_bundle(exe, "arm64", "1.2.3", self.dir, self.dir)  # the zip
        self.zip = zipfile.ZipFile(self.named)  # read back
        self.addCleanup(self.zip.close)  # closed before the folder goes

    def test_the_build_reads_the_version_from_the_one_place_it_is_written(self):
        from pkg_support import package_version  # the version as the package has it
        self.assertEqual(BUILD.package_version(), package_version())  # pyproject.toml has no version line of its own: it is dynamic

    def test_the_name_is_the_one_the_release_collects(self):
        self.assertEqual(self.named.name, "Offerowl-macos-arm64.zip")  # release.yml takes Offerowl-*

    def test_the_program_keeps_its_execute_bit(self):
        info = self.zip.getinfo("Offerowl.app/Contents/MacOS/Offerowl")  # the program's entry
        self.assertEqual(info.create_system, 3)  # Unix modes count
        self.assertTrue(stat.S_IMODE(info.external_attr >> 16) & stat.S_IXUSR)  # a person can start it with a double-click

    def test_finder_is_told_what_to_start(self):
        plist = plistlib.loads(self.zip.read("Offerowl.app/Contents/Info.plist"))  # the description
        self.assertEqual(plist["CFBundleExecutable"], "Offerowl")  # the file in Contents/MacOS
        self.assertEqual(plist["CFBundlePackageType"], "APPL")  # an application
        self.assertEqual(plist["CFBundleShortVersionString"], "1.2.3")  # the version it was given
        self.assertTrue(plist["LSUIElement"])  # it lives by the clock, as on the other systems

    def test_finder_is_told_the_oldest_macos_the_wheels_run_on(self):
        site = self.dir / "site"  # a build's installed packages, as pip leaves them
        for name, tags in (("pillow-13.0.0", ["cp312-cp312-macosx_11_0_arm64"]), ("pypdfium2-5.14.0", ["py3-none-macosx_13_0_arm64"]),
                           ("pyobjc_core-13.0", ["cp312-cp312-macosx_10_13_universal2"]), ("pystray-0.19.5", ["py2.py3-none-any"])):
            info = site / f"{name}.dist-info"
            info.mkdir(parents=True)
            (info / "WHEEL").write_text("Wheel-Version: 1.0\n" + "".join(f"Tag: {t}\n" for t in tags), encoding="utf-8")
        self.assertEqual("13.0", BUILD.minimum_macos(site))  # the highest one: below it the app would fail inside
        exe = self.dir / "Offerowl"  # the same stand-in as setUp's
        with zipfile.ZipFile(BUILD.mac_bundle(exe, "arm64", "1.2.3", self.dir, self.dir, "13.0")) as z:  # bundled with it
            self.assertEqual("13.0", plistlib.loads(z.read("Offerowl.app/Contents/Info.plist"))["LSMinimumSystemVersion"])

    def test_a_build_with_no_platform_wheel_names_no_minimum(self):
        site = self.dir / "pure"  # only pure Python packages
        (site / "pystray-0.19.5.dist-info").mkdir(parents=True)
        (site / "pystray-0.19.5.dist-info" / "WHEEL").write_text("Tag: py2.py3-none-any\n", encoding="utf-8")
        self.assertIsNone(BUILD.minimum_macos(site))  # nothing to say, so the key is left out
        self.assertNotIn("LSMinimumSystemVersion", plistlib.loads(self.zip.read("Offerowl.app/Contents/Info.plist")))

    @unittest.skipIf(importlib.util.find_spec("PIL") is None, "Pillow is not installed: the build leaves the picture out, and says so")
    def test_the_icon_is_in_the_bundle(self):
        self.assertIn("Offerowl.app/Contents/Resources/offerowl.icns", self.zip.namelist())  # the file CFBundleIconFile names


if __name__ == "__main__":  # also runs alone
    unittest.main()
