"""
Privacy scan. No real name, address or local path in anything published.
=========================================================================
The owner's rule: never write a real name, a screen name, a location, a
network address, a device serial or a local folder path into this repository
or anything published from it. The only public name is CrystalHeeler.

    python tests/privacy_scan.py

Exit 1 when a tracked file holds a match. Commit author metadata is reported
but does not fail the run, because changing it needs a history rewrite and
that needs the owner's order.

This file excludes itself, the same way a linter does not lint its own rules.
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF = "tests/privacy_scan.py"

# The file content patterns. Each one is a hard failure.
PATTERNS = (
    ("an email address",
     re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("a Windows user folder",
     re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]|/[a-z]/Users/")),
    ("a MAC address",
     re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")),
    ("a device serial",
     re.compile(r"\b(?:serial|SERIAL)[-_ ]?(?:no|number|NO)?[:=]\s*\S{6,}")),
)

IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")

# 0.0.0.0 binds every interface. 127.0.0.1 is loopback. The 10.0.0.x and
# 192.168.50.x ranges are the made-up addresses the rule allows in examples.
IP_ALLOWED = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|10\.0\.0\.\d{1,3}|192\.168\.50\.\d{1,3})$")

# Names that may appear. Anything else that looks like a person is for the
# owner to judge, so this list stays short and explicit.
ALLOWED_NAMES = ("CrystalHeeler", "crystalheeler")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\n") if p.strip()]


def scan_files() -> int:
    findings = 0
    checked = 0

    for rel in tracked_files():
        if rel == SELF:
            continue
        path = os.path.join(REPO, rel)
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except (UnicodeDecodeError, OSError):
            continue    # binary, such as the icon
        checked += 1

        for n, line in enumerate(lines, 1):
            for label, pattern in PATTERNS:
                for hit in pattern.findall(line):
                    print(f"FAIL {rel}:{n}: {label}: {hit}")
                    findings += 1
            for hit in IPV4.findall(line):
                if not IP_ALLOWED.match(hit):
                    print(f"FAIL {rel}:{n}: an IP address: {hit}")
                    findings += 1

    print(f"Scanned {checked} tracked text files.")
    return findings


def report_commit_authors() -> int:
    """Report author names and addresses. Never fails the run."""
    try:
        out = subprocess.run(
            ["git", "log", "--format=%an <%ae>"], cwd=REPO,
            capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        return 0

    identities = sorted(set(l for l in out.stdout.split("\n") if l.strip()))
    flagged = [i for i in identities
               if not any(name in i for name in ALLOWED_NAMES)
               or re.match(r"^[A-Z][a-z]+ <", i)]

    print()
    print(f"Commit identities in this repository: {len(identities)}")
    for ident in identities:
        mark = "  WARN " if ident in flagged else "  ok   "
        print(f"{mark}{ident}")

    if flagged:
        print()
        print("WARNING: an identity above carries a real first name or address.")
        print("Commit metadata publishes on push. Changing it needs:")
        print("  1. git config user.name CrystalHeeler")
        print("  2. git config user.email <an address you are willing to publish>")
        print("  3. a history rewrite plus a force push for existing commits,")
        print("     which needs the owner's explicit order.")
    return 0


def main() -> int:
    print("Privacy scan")
    print("=" * 60)
    findings = scan_files()
    report_commit_authors()
    print()
    if findings:
        print(f"RESULT: {findings} finding(s) in tracked files.")
        print("The owner's only public name is CrystalHeeler.")
        return 1
    print("RESULT: no findings in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
