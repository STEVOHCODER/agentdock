import re
from dataclasses import dataclass


REDISTRIBUTION_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "Unlicense",
    # Set only by the importer when the repository owner is listed in
    # AGENTDOCK_FIRST_PARTY_OWNERS. It records an explicit operator claim of
    # ownership; it is not assignable through the public API.
    "OWNER-AUTHORIZED",
}
SCRIPT_EXTENSIONS = {".sh", ".bash", ".py", ".js", ".ts", ".ps1", ".bat", ".cmd"}
RISK_PATTERNS = [
    re.compile(r"\b(?:curl|wget)\b[^\n]{0,160}(?:\||&&|\|\|)\s*(?:sh|bash|python)", re.I),
    re.compile(r"\brm\s+-rf\s+(?:/|\$HOME|~)", re.I),
    re.compile(r"\b(?:eval|exec)\s*\([^\n]{0,200}(?:base64|atob)", re.I),
    re.compile(r"ignore (?:all )?(?:previous|prior) instructions", re.I),
]
SECRET_PATTERNS = [re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                   re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{24,}")]


@dataclass
class Evaluation:
    score: int
    status: str
    license_allowed: bool
    security_status: str
    security_findings: list[str]
    criteria: dict[str, int]


def evaluate_candidate(*, stars: int, trusted: bool, last_push_days: int | None,
                       skill_md: str, license_id: str, files: dict[str, bytes], threshold: int = 75) -> Evaluation:
    popularity = 15 if stars >= 2000 else 12 if stars >= 500 else 8 if stars >= 100 else 3 if stars > 0 else 0
    credibility = 20 if trusted else 10
    maintenance = 20 if last_push_days is not None and last_push_days <= 90 else 15 if last_push_days is not None and last_push_days <= 180 else 8 if last_push_days is not None and last_push_days <= 365 else 2
    quality = 20 if skill_md and "name:" in skill_md and "description:" in skill_md else 14 if skill_md else 0
    quality = min(quality + (4 if len(files) >= 2 else 0), 20)
    security_findings = scan_security(files)
    security = 15 if not security_findings else max(0, 15 - 5 * len(security_findings))
    license_allowed = license_id in REDISTRIBUTION_LICENSES
    licensing = 10 if license_allowed else 0
    criteria = {"popularity": popularity, "credibility": credibility, "maintenance": maintenance,
                "quality": quality, "security": security, "licensing": licensing}
    score = sum(criteria.values())
    if not license_id or license_id.lower() in {"unknown", "none", "noassertion"}:
        status = "pending_review"
    elif not license_allowed:
        status = "pending_review"
    elif security_findings:
        status = "quarantined"
    elif stars < 100 and not trusted:
        status = "pending_review"
    elif score >= threshold:
        status = "qualified"
    else:
        status = "pending_review"
    return Evaluation(score, status, license_allowed, "flagged" if security_findings else "clear", security_findings, criteria)


def scan_security(files: dict[str, bytes]) -> list[str]:
    findings: list[str] = []
    for path, raw in files.items():
        lower = path.lower()
        if lower.startswith(".env") or "/.env" in lower:
            findings.append(f"Environment file included: {path}")
        try:
            content = raw.decode("utf-8", errors="ignore")
        except AttributeError:
            content = str(raw)
        if any(lower.endswith(ext) for ext in SCRIPT_EXTENSIONS):
            for pattern in RISK_PATTERNS:
                if pattern.search(content):
                    findings.append(f"Risky command pattern in {path}")
                    break
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            findings.append(f"Possible secret in {path}")
    return sorted(set(findings))
