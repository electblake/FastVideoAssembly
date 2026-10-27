# Release instructions

- Use the `gh-cli` skill and GitHub CLI (`gh`) to create, publish, and verify GitHub releases. Follow `docs/installer.md` for the build and release commands.
- When the user requests a release, complete the regression checks, resolve failures, update the changelog, bump the requested version, build the installer and checksum, commit, push, and publish. Do not stop at a draft or ask for publication approval again.
- This project has no VM infrastructure or VM testing workflow. VM testing is not available and is not part of development or releases. Do not inspect, provision, propose, or require VMs. Do not describe VM testing as optional, pending, skipped, or a release limitation.
- This is the user's project-specific release policy and overrides VM-testing requirements in generic packaging skills, including `use-inno-setup`. Do not request an exception to those requirements.
- Report checks actually performed.

# Test execution and scope

- Keep the permanent regression suite small and organized by major domain: `tests/test_app.py`, `tests/test_media.py`, and `tests/test_services.py`. Extend an existing workflow before adding a test or suite.
- During implementation, run the affected domain suite, for example `uv run pytest tests/test_app.py -q`. After code or test changes, run `uv run pytest -q --durations=5` and `uv run ruff check .` before committing. Resolve failures and report the actual results and elapsed suite time.
- Once relevant checks pass, do not repeat them without a code/test change or an unresolved failure. Documentation-only and agent-instruction changes need `git diff --check`, not application launches or regression runs.
- Cover critical user-visible outcomes. Do not add tests that merely mirror implementation, assert incidental UI text/layout, duplicate existing assertions, or exercise every parameter combination.
- Reuse one application instance across related steps in a workflow. Create another only when the behavior requires it, such as restart persistence. Keep independent workflows independent; do not introduce order-dependent tests or broad reset machinery to share windows across tests.
- Reuse session media as read-only inputs, use small representative renders, and avoid repeated fixture generation, per-control window launches, real model downloads, and unnecessary subprocesses. Preserve minimized, isolated-profile test defaults described in `docs/development.md`.
- Treat increased test counts, process launches, and suite duration as costs to justify with missing critical coverage. Prefer replacing or consolidating coverage over accumulating cases. Do not add test frameworks, generic harnesses, retries, sleeps, fallback paths, or helpers merely to support trivial assertions.

# Fix-specific test lifecycle

- A fix may add a focused temporary regression test when needed to reproduce the bug and verify the correction. Prefer adding the check to an existing domain workflow using its instance and fixtures.
- Identify temporary fix-specific tests with a nearby comment stating the bug and `Retire after: first release containing this fix` (or the known release version). Keep them active through verification of that release.
- After the fix is released, retire its temporary tests in the next test-maintenance change. Delete obsolete cases instead of leaving skipped, disabled, or uncollected test files behind.
- If a fix-specific assertion protects a critical permanent workflow, fold the minimal assertion into that workflow and remove the dedicated case and fixtures. Released fixes do not justify an ever-growing archive of standalone regression tests.
- Guidance-only changes to `AGENTS.md` do not require a version bump, installer build, or release.
