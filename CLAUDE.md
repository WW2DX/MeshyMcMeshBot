# MeshyMcMeshBot

A community bot for a MeshCore public channel. It runs on a Raspberry Pi with
a Wio Tracker L1 (USB Companion firmware) connected over serial. See README.md
for architecture and deployment.

## Before making any changes

Check that the repo is up to date before you edit anything:

1. Run `git status --short --branch` to see the current branch and any
   uncommitted changes.
2. If a remote is configured (`git remote -v`), run `git fetch` and compare
   the branch with its upstream.
   - **Behind** and the working tree is clean: `git pull --ff-only`.
   - **Diverged**, or behind with uncommitted changes: stop and ask the user
     how to proceed. Don't merge, rebase or stash on your own.
3. If there are uncommitted changes you didn't make, tell the user before you
   start, so new work isn't mixed into theirs.

## With every change

- **CHANGELOG.md:** add an entry under `## [Unreleased]` in the right group
  (Added / Changed / Fixed / Removed) for anything user- or operator-visible.
- **docs/USER_GUIDE.md:** update it whenever a change affects what people on
  the mesh see or type: commands, their output, limits, scheduled posts, or
  mail/BBS behavior. Keep it in the voice of someone using the MeshCore app,
  not an operator.
- **README.md:** update it for install, configuration, hardware, or
  architecture changes.
- If a default in `meshymcmeshbot/config.py` changes, update the numbers
  quoted in the user guide to match.

## Working on the code

- Tests: `python -m pytest -q tests`
- Try it without a radio: `python -m meshymcmeshbot -c config.yaml --console`
- The target is Python 3.11 (Raspberry Pi OS Bookworm). Don't use newer syntax.
- Messages must fit in about 140 UTF-8 bytes. Use the helpers in `text.py`;
  never split by character count.
- New features go in `meshymcmeshbot/features/<name>.py` with a `setup(bot)`
  function, registered in `features/__init__.py`.
