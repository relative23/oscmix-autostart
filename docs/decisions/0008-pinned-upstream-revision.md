# 0008 -- The upstream backend is pinned, and the pin moves only after a measurement

**Status:** accepted (0.2.0)

## Decision

`install.sh` builds oscmix at a full 40-character commit SHA, and
verifies the checkout landed on exactly it. Tracking upstream is
possible but explicit: `OSCMIX_REF=master ./install.sh`.

**The pin may only be bumped together with a fresh hardware
measurement.** A bump commit that does not carry a new evidence artifact
is not a bump, it is an unpinning spread over time.

## Why pin

Before this, `install.sh` built `OSCMIX_REF=master` -- whatever upstream
happened to be that day. That makes the word "verified" hollow: a
measurement is evidence about the binary it was taken against, and
nothing else. Every hardware claim in this repository was made against
one build of oscmix, and there was no way to say which.

It is also the only path here that fetches and compiles code from the
network, which is worth being deliberate about on its own.

No signature verification: upstream publishes no signed tags. That is
exactly why the default is a *commit that has been measured* rather than
a branch -- the pin is doing the job a signature would not have done
anyway.

## Why a bump needs a measurement

Three bumps without measurements restore the situation the pin was
introduced to end, one small step at a time, while the repository still
claims to be pinned. The artifact would then describe a binary that is
no longer shipped, which is worse than no artifact: it reads as evidence.

The backend is not an ordinary dependency. Three of this project's
timing constants -- `LINK_ECHO_TIMEOUT`, `LINK_SETTLE`,
`LINK_SYNC_BLIND_DELAY` -- exist solely because of one upstream
implementation detail (`setbool` does not update oscmix's own register
cache). A revision that changed that detail would change what is correct
here, silently and at message level only, which is the shape all three
defects fixed in 0.1.3 had.

The same rule governs the upstream work item: if the
cache-synchronisation patch is accepted, the order is **bump, measure,
then** delete those three constants. Not the other way round.

## Consequences for install.sh

The pin cost the shallow clone: `git clone --depth 1 --branch` accepts a
branch or a tag but not a commit. `git init` + `git remote add` +
`git fetch --depth 1 origin <sha>` does take a commit, so the shallow
clone is back -- one commit instead of the full history. Measured
against upstream today: 480K versus 632K of `.git`, both under a second.
The size is not the point; the property is, and it matters more as
upstream's history grows.

A server may refuse to serve an arbitrary SHA
(`uploadpack.allowReachableSHA1InWant`). GitHub does not, but a mirror
might, so a failed shallow fetch warns and falls back to a full clone
rather than aborting the install.

## What this rules out

- Bumping the pin in a dependency-update commit, or by a bot.
- A release whose evidence artifact names a different revision than
  `install.sh` builds. The release checklist checks this.
- Treating "CI builds it fine" as sufficient. CI has no Fireface
  attached; it proves the code compiles, not that the device does what
  the routing says.

## Enforced by

- `install.sh` verifies `git rev-parse HEAD` equals the pinned SHA when
  the ref is a full SHA.
- The `build-oscmix` job in CI extracts the SHA from `install.sh` and
  builds exactly it, so a pin that no longer resolves fails the build.
- `scripts/verify-hardware.py` records the built revision in the
  evidence artifact.
- `docs/RELEASE-CHECKLIST.md` requires the artifact's revision and the
  pinned revision to match before a tag.
