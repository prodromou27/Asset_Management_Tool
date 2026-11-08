import copy
import unittest

from gate import evaluate

BASE = {
    "SchemaVersion": 2,
    "Metadata": {"OS": {"Family": "debian", "EOSL": False}},
    "Results": [
        {"Type": "uv", "Packages": [{"Name": "Django"}, {"Name": "pytest"}]},
        {"Type": "debian", "Class": "os-pkgs", "Packages": [{"Name": "libc6"}]},
    ],
}


class SecurityGateTests(unittest.TestCase):
    def go_report(self):
        report = copy.deepcopy(BASE)
        report["Results"].append(
            {
                "Type": "gobinary",
                "Target": "usr/local/bin/restic",
                "Packages": [
                    {"Name": "github.com/restic/restic", "Version": "v0.18.1"},
                    {"Name": "stdlib", "Version": "v1.27.3"},
                ],
            }
        )
        return report

    def test_requires_compiler_and_module_in_the_exact_binary(self):
        required = {"usr/local/bin/restic": ("github.com/restic/restic", "stdlib")}
        result = evaluate(self.go_report(), required_binaries=required)
        self.assertEqual(result["binaries"]["usr/local/bin/restic"]["stdlib"], "v1.27.3")
        with self.assertRaises(ValueError):
            evaluate(BASE, required_binaries=required)
        report = self.go_report()
        report["Results"][-1]["Target"] = "another/binary"
        with self.assertRaises(ValueError):
            evaluate(report, required_binaries=required)

    def test_partial_unversioned_or_ambiguous_binary_coverage_fails(self):
        required = {"usr/local/bin/restic": ("github.com/restic/restic", "stdlib")}
        for version in (None, "", "(devel)", "unknown", "   ", 1):
            report = self.go_report()
            report["Results"][-1]["Packages"][1]["Version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                evaluate(report, required_binaries=required)
        report = self.go_report()
        report["Results"].append(copy.deepcopy(report["Results"][-1]))
        with self.assertRaises(ValueError):
            evaluate(report, required_binaries=required)

    def test_binary_findings_still_hold_even_when_coverage_is_complete(self):
        report = self.go_report()
        report["Results"][-1]["Vulnerabilities"] = [
            {
                "VulnerabilityID": "GO-fixture",
                "PkgName": "stdlib",
                "Severity": "HIGH",
            }
        ]
        self.assertEqual(
            evaluate(
                report,
                required_binaries={
                    "usr/local/bin/restic": ("github.com/restic/restic", "stdlib"),
                },
            )["status"],
            "held",
        )

    def test_reviewed_sqlite_os_version_is_required(self):
        required = {"sqlite-libs": "3.54.1-r0"}
        report = copy.deepcopy(BASE)
        for version in (None, "3.53.4-r0", "3.54.1-r0"):
            report["Results"][1]["Packages"] = [{"Name": "sqlite-libs", "Version": version}]
            if version == "3.54.1-r0":
                self.assertEqual(
                    evaluate(report, required_os_versions=required)["status"], "passed"
                )
            else:
                with self.assertRaises(ValueError):
                    evaluate(report, required_os_versions=required)

    def test_valid_coverage_without_findings(self):
        self.assertEqual(
            evaluate(BASE, required_type="uv", required_packages=("django", "pytest"))["status"],
            "passed",
        )

    def test_unfixed_high_and_critical_are_not_suppressed(self):
        for severity in ("HIGH", "CRITICAL"):
            with self.subTest(severity=severity):
                report = copy.deepcopy(BASE)
                report["Results"][0]["Vulnerabilities"] = [
                    {"VulnerabilityID": "CVE-fixture", "PkgName": "example", "Severity": severity}
                ]
                result = evaluate(report)
                self.assertEqual(result["status"], "held")
                self.assertEqual(result["findings"][0]["FixedVersion"], "")

    def test_lower_severity_stays_visible(self):
        for severity in ("LOW", "MEDIUM", "UNKNOWN"):
            with self.subTest(severity=severity):
                report = copy.deepcopy(BASE)
                report["Results"][0]["Vulnerabilities"] = [
                    {"VulnerabilityID": "fixture", "PkgName": "example", "Severity": severity}
                ]
                result = evaluate(report)
                self.assertEqual(result["counts"][severity], 1)
                self.assertEqual(len(result["findings"]), 1)

    def test_missing_or_empty_report_fails_closed(self):
        for report in (
            None,
            {},
            {"SchemaVersion": 2, "Results": []},
            {"SchemaVersion": 2, "Results": ["bad"]},
        ):
            with self.subTest(report=report), self.assertRaises(ValueError):
                evaluate(report)

    def test_missing_development_coverage_is_not_clean(self):
        with self.assertRaises(ValueError):
            evaluate(BASE, required_type="pnpm")
        with self.assertRaises(ValueError):
            evaluate(BASE, required_packages=("vite",))

    def test_unsupported_severity_does_not_disappear(self):
        report = copy.deepcopy(BASE)
        report["Results"][0]["Vulnerabilities"] = [{"Severity": "bad"}]
        with self.assertRaises(ValueError):
            evaluate(report)

    def test_unknown_os_is_not_a_clean_image(self):
        report = copy.deepcopy(BASE)
        report["Metadata"] = {}
        with self.assertRaises(ValueError):
            evaluate(report, image=True)

    def test_end_of_support_os_blocks_even_without_cves(self):
        report = copy.deepcopy(BASE)
        report["Metadata"]["OS"]["EOSL"] = True
        result = evaluate(report, image=True)
        self.assertEqual(result["status"], "held")
        self.assertTrue(result["end_of_support"])


if __name__ == "__main__":
    unittest.main()
