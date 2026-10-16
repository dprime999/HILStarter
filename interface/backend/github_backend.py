from __future__ import annotations

import argparse
import os
import re
from urllib.parse import urlparse

from common import BackendError, print_json, run, save_state


def normalize_repo(value: str) -> str:
    value = value.strip()
    if value.startswith("git@") or value.startswith("https://") or value.startswith("http://"):
        return value
    if value.count("/") == 1:
        return f"https://github.com/{value}.git"
    raise BackendError("repo must be owner/name or a git URL")


def repo_label(url: str) -> str:
    if url.startswith("git@"):
        path = url.split(":", 1)[1]
    else:
        path = urlparse(url).path.lstrip("/")
    return path.removesuffix(".git")


def discover_default_branch(repo: str) -> str:
    result = run(["git", "ls-remote", "--symref", repo, "HEAD"], timeout=45)
    if not result.ok:
        raise BackendError(result.stderr or "could not read repository HEAD")
    for line in result.stdout.splitlines():
        match = re.match(r"ref:\s+refs/heads/([^\s]+)\s+HEAD$", line)
        if match:
            return match.group(1)
    raise BackendError("could not determine repository default branch")


def verify_branch(repo: str, branch: str) -> tuple[bool, str]:
    result = run(["git", "ls-remote", "--exit-code", "--heads", repo, branch], timeout=45)
    return result.ok and bool(result.stdout.strip()), result.stderr


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate GitHub repository access and discover the default branch when one is not supplied."
    )
    p.add_argument("--project", required=True)
    p.add_argument("--repo", required=True, help="owner/name or clone URL")
    p.add_argument("--branch", help="optional; defaults to the repository's default branch")
    p.add_argument("--token-env", default="GITHUB_TOKEN", help="optional PAT environment variable; never persisted")
    p.add_argument("--skip-check", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    repo = normalize_repo(args.repo)
    token_present = bool(os.environ.get(args.token_env))

    branch = args.branch
    check_error = ""
    if not args.skip_check:
        try:
            branch = branch or discover_default_branch(repo)
            ok, check_error = verify_branch(repo, branch)
        except BackendError as exc:
            ok = False
            check_error = str(exc)
    else:
        branch = branch or "HEAD"
        ok = True

    state = {
        "step": "github",
        "status": "confirmed" if ok else "access_failed",
        "repo": repo,
        "repo_label": repo_label(repo),
        "branch": branch,
        "branch_was_user_supplied": bool(args.branch),
        "token_env": args.token_env,
        "token_present_at_check": token_present,
        "credential_persisted": False,
        "check_error": check_error if not ok else "",
    }
    save_state(args.project, "github_state", state)
    print_json(state)
    return 0 if ok else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BackendError as exc:
        print_json({"status": "error", "error": str(exc)})
        raise SystemExit(2)
