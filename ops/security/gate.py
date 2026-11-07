"""Fail closed on missing coverage and HIGH/CRITICAL findings; no suppression list."""

SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def evaluate(report, *, required_type=None, required_packages=(), image=False):
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2:
        raise ValueError("Missing or unsupported scan schema")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Missing scan results")
    if any(not isinstance(row, dict) for row in results):
        raise ValueError("Malformed result entry")
    covered = [row for row in results if required_type is None or row.get("Type") == required_type]
    packages = {p.get("Name", "").casefold() for row in covered for p in row.get("Packages", [])}
    if not covered or not packages or not set(required_packages).issubset(packages):
        raise ValueError("Required package coverage was not reported")
    if image:
        os = report.get("Metadata", {}).get("OS", {})
        if not os.get("Family"):
            raise ValueError("Image operating system was not identified")
        if not any(row.get("Class") == "os-pkgs" and row.get("Packages") for row in results):
            raise ValueError("Image OS package coverage was not reported")
    eosl = bool(image and report.get("Metadata", {}).get("OS", {}).get("EOSL"))
    counts = dict.fromkeys(sorted(SEVERITIES), 0)
    findings = []
    for row in results:
        for item in row.get("Vulnerabilities") or []:
            severity = item.get("Severity")
            if (
                severity not in SEVERITIES
                or not item.get("VulnerabilityID")
                or not item.get("PkgName")
            ):
                raise ValueError("Malformed vulnerability entry")
            counts[severity] += 1
            findings.append(
                {
                    key: item.get(key, "")
                    for key in (
                        "VulnerabilityID",
                        "PkgName",
                        "InstalledVersion",
                        "FixedVersion",
                        "Severity",
                        "PrimaryURL",
                    )
                }
            )
    return {
        "status": "held" if eosl or counts["HIGH"] or counts["CRITICAL"] else "passed",
        "end_of_support": eosl,
        "packages": len(packages),
        "counts": counts,
        "findings": findings,
    }
