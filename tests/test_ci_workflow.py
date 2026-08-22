"""Hygiene rules for the CI workflow itself.

Written after a job with no `timeout-minutes` hung on `sudo apt-get
update` and burned GitHub's 360-minute default -- six hours, on a job
whose measured maximum is under seven minutes. Four of the six jobs had
no timeout at the time; nothing said they should.

Parsed textually rather than with PyYAML, which is not a dev dependency
and would be a lot of weight for this. A textual parse can silently find
nothing and pass, so the test asserts it found the jobs it expects
before it asserts anything about them -- otherwise a formatting change
would turn this into a test that always succeeds.
"""

import re

from conftest import repo_file

WORKFLOW = ("quality", "test", "coverage", "flake", "mutation",
            "build-oscmix")


def _jobs(name="ci.yml"):
    """Job id -> its block of the workflow, for jobs that run somewhere."""
    text = repo_file(".github", "workflows", name).read_text()
    blocks = re.split(r"\n  (?=[\w-]+:\n)", text)
    found = {}
    for block in blocks:
        match = re.match(r"\s*([\w-]+):", block)
        if match and "runs-on:" in block:
            found[match.group(1)] = block
    return found


def test_the_parse_finds_the_jobs_it_is_about_to_judge():
    # The guard on the guard. Without it, a reformat that breaks the
    # regex makes every assertion below vacuously true.
    assert set(_jobs()) == set(WORKFLOW)


def test_every_ci_job_has_a_timeout():
    """No job may inherit GitHub's 360-minute default.

    That default is not a ceiling anybody chose for this repository. It
    was reached once, by `sudo apt-get update` hanging on a runner, on
    the one job that builds upstream -- and the run sat there for six
    hours before GitHub killed it.
    """
    missing = sorted(job for job, block in _jobs().items()
                     if "timeout-minutes:" not in block)
    assert missing == [], (
        "these inherit the 360-minute default: %s" % missing)


def test_no_timeout_is_anywhere_near_the_default():
    """A timeout of 300 would be a default with extra steps.

    Each one is meant to catch a hang, so it belongs just above the
    job's measured maximum -- the numbers are recorded in the workflow
    next to them. 90 for the mutation job is the largest, against a
    measured 46.5.
    """
    too_generous = {}
    for job, block in _jobs().items():
        found = re.search(r"timeout-minutes:\s*(\d+)", block)
        if found and int(found.group(1)) > 120:
            too_generous[job] = int(found.group(1))
    assert too_generous == {}, (
        "these are long enough to hide a hang: %s" % too_generous)


# --------------------------------------------------------------------------
# The concurrency group, which decides whether a commit is tested at all.
# --------------------------------------------------------------------------

def _concurrency(name="ci.yml"):
    """The `concurrency:` block, comments stripped and folded to one line.

    `group:` is a folded scalar over two lines, so a test that matched
    the raw text would break on a rewrap rather than on a change of
    meaning.
    """
    text = repo_file(".github", "workflows", name).read_text()
    match = re.search(r"\nconcurrency:\n(.*?)\n\w", text, re.DOTALL)
    assert match, "no concurrency block -- this test judges nothing"
    body = [line.split("#")[0] for line in match.group(1).splitlines()]
    return " ".join(" ".join(body).split())


def test_a_push_gets_its_own_concurrency_group():
    """Otherwise a commit can reach main having run no jobs at all.

    A group holds one running run and one queued run, and a third
    arrival cancels the queued one. Three pushes to main inside an hour
    did exactly that: the middle run reported `cancelled` with zero jobs
    and nothing was ever tested on that commit. Keying the group on the
    commit means no push run can ever be queued behind another.
    """
    assert "github.sha" in _concurrency()


def test_a_pull_request_still_supersedes_its_own_older_revisions():
    """The behaviour the group existed for in the first place: pushing a
    fix to a PR should not leave the previous revision burning runners.
    Both halves have to be there, so the fix above cannot be "drop the
    grouping entirely"."""
    group = _concurrency()
    assert "github.ref" in group
    assert "github.event_name == 'pull_request'" in group
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" \
        in group
