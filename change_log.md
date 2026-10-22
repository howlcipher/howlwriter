# Change Log

## Unreleased

* Pin the `plane` extra and the real integration CI checkout to reviewed HowlPlane `20b110a`, including malformed-state exit and published Frame artifact compatibility corrections. The CI checkout previously followed moving `main` despite being labeled pinned; it now tests the same immutable revision the extra installs.

* Pin shared howl-provider-core `9bf1f78`, matching HowlDream and HowlCreate, restoring historical credential coverage and sanitizing provider failure metadata before persistence (Mission 007 F2).
* Invalid `runs prune` retention arguments now exit 1, including conflicting flags, negative settings, and overflowing day counts; synthetic regression tests verify no run artifacts change (F10).
* Keep portability-test environment isolation intact while testing unavailable and unconfigured HowlPlane.

* `howlwriter interop --json` prints the `howl.interop/v1` descriptor from the Howl interop contract: every command and flag (from the live parser), the documents `native request|write` produce, and the exit codes. HowlPlane and `howl doctor` use it to check the commands they run.
* A model chosen with `--provider` (or `HOWLWRITER_PROVIDER`, or the page) when HowlPlane cannot be imported now fails with exit 1 and names the missing package (web: HTTP 503 `howlplane_unavailable`). Before, it reported "needs a model" with exit 2, and steps with a rule-based path silently ran that path instead of the chosen model.
* A usage error (unknown flag or subcommand) exits 1 instead of argparse's 2, so 2 means only "a model step had no model chosen" (or the remote gate) and a caller such as HowlPlane cannot mistake an unsupported flag for a request for input.
* `HOWLPLANE_HOME` and `HOWLPLANE_DIR`, HowlPlane's own names for its checkout, are a fallback when `HOWLPLANE_ROOT` is unset and no installed HowlPlane can be imported; they never shadow an installed HowlPlane. New optional extra `howlwriter[plane]` installs HowlPlane for a plain pip install.

* Lines read from a data file (CSV, logs, JSON) are `directly_observed` only while the file is classified as experimental evidence; in any other category they are `extracted_from_source`, and the status follows a category change (the next scan updates an existing project). A parsed rating table or a reference's figures no longer read as the user's own measurements. Both statuses still count as fact.
* `project classify` and the category API record who set the category: `user` at a terminal or in HowlWriter's page, `owner_relayed` with `--owner-confirmed` (or `X-HowlWriter-Owner-Confirmed: 1`), and `agent` otherwise, instead of `user` for everyone. Each survives rescans as before.
* Document that a derived data table (ratings, a findings ledger) in `evidence/` must be classified as a draft or reference to stop counting as direct observation; the classifier goes by format and folder and cannot tell.
* Name the real cause when HowlPlane is found but cannot be imported (for instance a dependency of its own is missing in the Python HowlWriter runs in): model steps and the model menu now report the failed import and the Python path instead of "not configured" or "not installed".
* Read requirements from wrapped text, such as slide or column extraction, as whole sentences: wrapped lines are rejoined, a lead-in such as "You must include:" keeps the list after it (or gives way to its bullets), and "Please choose ..." and "you will create ..." instructions are found. Requirement IDs come from their text, so a rescan of such a project gives the changed rows new IDs and drops a status set by hand on the old ones; set those again.
* Keep the draft when a writer reply's YAML does not parse. A small model often indents only the first line under `body_markdown: |`; the whole reply (fence, keys and claim lists) then became the draft. The writer, outline writer, length correction and project draft now recover the body, and the claim lists when they parse.
* `writer` without `--sources` no longer asks the model for APA citations, which led small models to invent authors, years and figures; it asks for none. It also warns on stderr about any in-text citation that matches no supplied source and any exact identifier (such as a CVE) found in neither the sources nor the prompt, and `writer --fail-if-blocked` exits 3 on either.
* Add `project draft --fail-if-blocked`, which exits 3 when the draft's own validation verdict is not ready. Without it the exit code is unchanged (0, with the verdict in the output).
* Discover explicitly selected HowlPlane source checkouts using the current src/howlplane/control_plane layout while preserving installed packages and the legacy source layout.
* Show concrete environment binding and source checkout instructions in writer help and model role configuration errors.
* Correct onboarding documentation to reflect the existing environment based default role registry rather than claiming automatic configuration file loading.
* Add isolated process regressions for current, legacy, and installed discovery, absent packages, missing bindings, and public writer help. Discovery never executes a provider.
* Use SPDX MIT license metadata and a compatible setuptools floor so fresh wheel builds avoid deprecated license table warnings.
* Declare httpx2 as a development dependency for the current Starlette TestClient, avoiding its deprecated httpx fallback in fresh native test environments.
