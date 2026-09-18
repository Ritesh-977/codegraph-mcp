"""Credential handling — the security-critical surface of Phase 6.2.

Uses fake tokens only. A real credential must never appear in this repo.
"""

from __future__ import annotations

import pytest

from codegraph.config import Settings
from codegraph.ingestion.git import authed_url, repo_slug_from_url, sanitize_url, scrub

_FAKE = "ghp_TESTNOTREAL0000"


# --- sanitize_url --------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (f"https://{_FAKE}@github.com/acme/app", "https://github.com/acme/app"),
        (f"https://user:{_FAKE}@github.com/acme/app.git", "https://github.com/acme/app.git"),
        (f"https://oauth2:{_FAKE}@git.corp.internal/acme/app", "https://git.corp.internal/acme/app"),
        ("https://github.com/acme/app", "https://github.com/acme/app"),  # already clean
        ("git@github.com:acme/app.git", "git@github.com:acme/app.git"),  # ssh untouched
    ],
)
def test_sanitize_url_strips_credentials(raw: str, expected: str) -> None:
    out = sanitize_url(raw)
    assert out == expected
    assert _FAKE not in out


# --- scrub ---------------------------------------------------------------

def test_scrub_redacts_token_from_git_error() -> None:
    """A failed clone re-raises a message containing the URL it was given."""
    err = (
        f"Cmd('git') failed: git clone https://{_FAKE}@github.com/acme/private "
        "stderr: 'remote: Invalid username or password.'"
    )
    out = scrub(err, _FAKE)
    assert _FAKE not in out
    assert "Invalid username or password" in out, "must stay diagnosable"


def test_scrub_removes_userinfo_even_without_a_known_secret() -> None:
    out = scrub("failed: https://someone:hunter2@host/x")
    assert "hunter2" not in out


# --- token injection -----------------------------------------------------

def test_token_injected_for_https() -> None:
    assert authed_url("https://github.com/acme/app", _FAKE) == (
        f"https://{_FAKE}@github.com/acme/app"
    )


def test_token_not_injected_into_ssh_urls() -> None:
    """SSH authenticates with keys; an embedded token would be meaningless."""
    ssh = "git@github.com:acme/app.git"
    assert authed_url(ssh, _FAKE) == ssh


def test_token_scoped_to_its_host() -> None:
    """A GitHub token must not be sent to an internal GitLab just because it
    happened to be cloned next."""
    internal = "https://git.corp.internal/acme/app"
    assert authed_url(internal, _FAKE, token_host="github.com") == internal
    assert _FAKE in authed_url("https://github.com/acme/app", _FAKE, token_host="github.com")


def test_no_token_configured_is_a_no_op() -> None:
    url = "https://github.com/acme/app"
    assert authed_url(url, None) == url


# --- graph_id must never carry a credential ------------------------------

def test_slug_from_tokenized_url_has_no_credential() -> None:
    """The host capture group would otherwise grab `ghp_xxx@github.com`."""
    slug = repo_slug_from_url(f"https://{_FAKE}@github.com/acme/app")
    assert slug == "github.com/acme/app"
    assert _FAKE not in slug


# --- the leak regression: nothing reaches the graph ----------------------

def test_token_never_appears_in_the_ingest_plan() -> None:
    """cli.py sanitizes before build_ingest_plan; this pins that a tokenized
    URL cannot end up in Neo4j via `SET r.url = $url` (and be handed to the
    LLM by list_repos)."""
    from codegraph.ingestion.git import sanitize_url as clean
    from codegraph.ingestion.graph_builder import build_ingest_plan

    raw = f"https://{_FAKE}@github.com/acme/app"
    plan = build_ingest_plan(
        slug=repo_slug_from_url(raw),
        url=clean(raw),
        branch="main",
        files=[],
        commits={},
        known_paths=set(),
    )
    blob = repr(plan)
    assert _FAKE not in blob, "token leaked into the ingest plan"


# --- Settings ------------------------------------------------------------

def test_settings_repr_does_not_reveal_token() -> None:
    """An accidental log/print of Settings must not dump the credential."""
    s = Settings(git_token=_FAKE)
    assert _FAKE not in repr(s)
    assert _FAKE not in str(s)
    assert s.git_token is not None
    assert s.git_token.get_secret_value() == _FAKE


# --- per-host token userinfo forms ---------------------------------------

@pytest.mark.parametrize(
    "url,expected_userinfo",
    [
        # GitHub takes a bare token; Bitbucket and GitLab reject that and need
        # a username component, so a bare token silently fails to authenticate.
        ("https://github.com/acme/app", f"{_FAKE}@"),
        ("https://bitbucket.org/acme/app", f"x-token-auth:{_FAKE}@"),
        ("https://gitlab.com/acme/app", f"oauth2:{_FAKE}@"),
    ],
)
def test_token_userinfo_matches_host_convention(url: str, expected_userinfo: str) -> None:
    assert expected_userinfo in authed_url(url, _FAKE)


def test_explicit_username_overrides_host_default() -> None:
    """Bitbucket app passwords use your real username, not x-token-auth; a
    self-hosted Gitea may want a service account."""
    out = authed_url("https://bitbucket.org/acme/app", _FAKE, username="ritesh")
    assert f"ritesh:{_FAKE}@" in out
    assert "x-token-auth" not in out


def test_self_hosted_host_gets_bare_token_unless_username_given() -> None:
    assert authed_url("https://git.corp.internal/a/b", _FAKE) == (
        f"https://{_FAKE}@git.corp.internal/a/b"
    )
