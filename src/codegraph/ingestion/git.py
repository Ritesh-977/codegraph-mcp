"""Git operations: clone/fetch + default-branch resolution.

Uses GitPython. The clone itself is network I/O — unit tests cover pure URL parsing;
integration is exercised end-to-end via the ingest CLI against a fixture dir.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import stat
from pathlib import Path

from git import Repo

from codegraph.paths import local_repo_dir

_URL_RE = re.compile(r"(?:https://|git@)(?P<host>[^/:]+)[:/](?P<path>.+?)(?:\.git)?$")

# Userinfo in an https URL — `https://user:token@host/...` or `https://token@host/...`
_USERINFO_RE = re.compile(r"\b(https?://)[^/\s@]*@", re.IGNORECASE)

_REDACTED = "***"

# Hosts disagree on how a token is presented in an https URL. GitHub takes a
# bare token; Bitbucket and GitLab require a username component, so a bare
# token silently fails to authenticate there.
_DEFAULT_TOKEN_USERS = {
    "bitbucket.org": "x-token-auth",
    "gitlab.com": "oauth2",
}


def sanitize_url(url: str) -> str:
    """Strip any embedded credentials from a URL.

    `https://ghp_xxx@github.com/a/b` -> `https://github.com/a/b`. Applied before
    a URL is parsed, stored in the graph, logged, or echoed — a token must never
    survive into Neo4j or stderr.
    """
    return _USERINFO_RE.sub(r"\1", url.strip())


def scrub(text: str, secret: str | None = None) -> str:
    """Redact credentials from arbitrary text (git error messages, mostly).

    Removes a known secret if one is configured, and any URL userinfo, since a
    failed clone re-raises a message containing the URL it was given.
    """
    out = text
    if secret:
        out = out.replace(secret, _REDACTED)
    return _USERINFO_RE.sub(r"\1", out)


def authed_url(
    url: str, token: str | None, token_host: str = "", username: str = ""
) -> str:
    """Return `url` with `token` embedded, or `url` unchanged.

    Only applies to https URLs — ssh/`git@` uses keys. When `token_host` is set
    the token is injected only for that host, so a GitHub token isn't handed to
    an internal GitLab just because it happened to be cloned next.

    Hosts disagree on the userinfo form, so `username` is configurable:
    GitHub accepts a bare `token@`, Bitbucket needs `x-token-auth:token@`
    (or `user:app_password@`), GitLab wants `oauth2:token@`. When no username
    is given the default host conventions are applied.
    """
    if not token or not url.strip().lower().startswith("http"):
        return url
    clean = sanitize_url(url)
    m = _URL_RE.match(clean)
    if not m:
        return url
    host = m.group("host").lower()
    if token_host and host != token_host.strip().lower():
        return url
    user = username.strip() or _DEFAULT_TOKEN_USERS.get(host, "")
    userinfo = f"{user}:{token}" if user else token
    scheme, rest = clean.split("://", 1)
    return f"{scheme}://{userinfo}@{rest}"


def _force_remove_tree(dest: Path) -> None:
    """Delete a cloned repo tree, including Git's read-only pack files.

    Git marks objects under `.git/objects/pack` read-only. On Windows that
    makes `shutil.rmtree` fail with PermissionError (WinError 5), so grant
    write permission across the tree first. Bits are OR-ed onto the existing
    mode so directories keep their traversal (execute) bit on POSIX.
    """
    for p in dest.rglob("*"):
        with contextlib.suppress(OSError):
            p.chmod(p.stat().st_mode | stat.S_IWRITE)
    shutil.rmtree(dest)


def repo_slug_from_url(url: str) -> str:
    """`https://github.com/acme/app` -> `github.com/acme/app`.

    Host-qualified: without it, github.com/acme/app and an internal
    gitlab/acme/app collapse to the same graph_id and silently merge into one
    graph. Sanitizing first also keeps an embedded token out of the id — the
    host group would otherwise capture `ghp_xxx@github.com`.
    """
    clean = sanitize_url(url)
    m = _URL_RE.match(clean)
    if not m:
        # Report the sanitized URL: the raw one may carry a credential.
        raise ValueError(f"unparseable repo URL: {clean!r}")
    return f"{m.group('host')}/{m.group('path')}"


def local_path_for(url: str, repos_dir: Path) -> Path:
    return local_repo_dir(repo_slug_from_url(url), repos_dir)


def clone_or_fetch(
    url: str,
    dest: Path,
    branch: str | None,
    depth: int,
    force: bool = False,
    token: str | None = None,
    token_host: str = "",
    token_username: str = "",
) -> str:
    """Clone (or fetch+reset) into dest; return the resolved default branch name.

    `force=True` removes any existing local clone first, so a corrupt or stale
    cache always falls through to a fresh `clone_from` instead of fetch+reset.

    Auth: SSH keys and OS credential helpers work with no `token` at all, since
    git inherits this process's environment. A `token` is for headless/CI use;
    it is embedded only for the duration of the network call and never written
    to `.git/config`. Any git error is scrubbed before it propagates, because
    the message would otherwise echo the URL it was given.
    """
    clean = sanitize_url(url)
    remote = authed_url(clean, token, token_host, token_username)
    try:
        return _clone_or_fetch_inner(clean, remote, dest, branch, depth, force)
    except Exception as exc:
        raise RuntimeError(scrub(str(exc), token)) from None


def _clone_or_fetch_inner(
    clean: str, remote: str, dest: Path, branch: str | None, depth: int, force: bool
) -> str:
    if force and dest.exists():
        _force_remove_tree(dest)
    if dest.exists() and (dest / ".git").exists():
        repo = Repo(str(dest))
        _deepen_if_needed(repo, dest, depth)
        # Fetch by explicit URL: the stored remote is deliberately credential-free,
        # so it can't authenticate on its own.
        repo.git.fetch(remote, "+refs/heads/*:refs/remotes/origin/*")
        br = branch or _detect_default(repo)
        repo.git.checkout(br)
        repo.git.reset("--hard", f"origin/{br}")
        return br
    # depth=0 means full history; `--depth=0` is not the same thing to git, so
    # the flag is omitted entirely rather than passed a falsy value.
    shallow = bool(depth and depth > 0)
    if branch:
        if shallow:
            repo = Repo.clone_from(remote, str(dest), depth=depth, branch=branch)
        else:
            repo = Repo.clone_from(remote, str(dest), branch=branch)
        _strip_remote_credentials(repo, clean)
        return branch
    if shallow:
        repo = Repo.clone_from(remote, str(dest), depth=depth)
    else:
        repo = Repo.clone_from(remote, str(dest))
    _strip_remote_credentials(repo, clean)
    return _detect_default(repo)


def _strip_remote_credentials(repo: Repo, clean_url: str) -> None:
    """Point origin at the credential-free URL immediately after cloning.

    Without this the token stays in `.git/config` on disk for the life of the
    clone, readable by anything that can read the repo.
    """
    with contextlib.suppress(Exception):
        repo.remotes.origin.set_url(clean_url)


def _deepen_if_needed(repo: Repo, dest: Path, depth: int) -> None:
    """Convert an existing shallow clone to full history when depth=0.

    Without this, a repo cloned under the old depth-1 default keeps its single
    commit forever, so every file would keep reporting the same author/date
    even after re-ingesting.
    """
    if depth and depth > 0:
        return
    if not (dest / ".git" / "shallow").exists():
        return
    with contextlib.suppress(Exception):
        # Errors on an already-complete repo, hence the guard above and here.
        repo.git.fetch("--unshallow")


def _detect_default(repo: Repo) -> str:
    try:
        return repo.head.ref.name
    except Exception:
        try:
            out: str = str(repo.git.symbolic_ref("refs/remotes/origin/HEAD"))
            return out.replace("refs/remotes/origin/", "")
        except Exception:
            return "main"
