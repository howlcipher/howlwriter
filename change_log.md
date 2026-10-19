# Change Log

## Unreleased

* Name the real cause when HowlPlane is found but cannot be imported (for instance a dependency of its own is missing in the Python HowlWriter runs in): model steps and the model menu now report the failed import and the Python path instead of "not configured" or "not installed".
* Read requirements from wrapped text, such as slide or column extraction, as whole sentences: wrapped lines are rejoined, a lead-in such as "You must include:" keeps the list after it (or gives way to its bullets), and "Please choose ..." and "you will create ..." instructions are found. Requirement IDs come from their text, so a rescan of such a project gives the changed rows new IDs and drops a status set by hand on the old ones; set those again.
* Add `project draft --fail-if-blocked`, which exits 3 when the draft's own validation verdict is not ready. Without it the exit code is unchanged (0, with the verdict in the output).
* Discover explicitly selected HowlPlane source checkouts using the current src/howlplane/control_plane layout while preserving installed packages and the legacy source layout.
* Show concrete environment binding and source checkout instructions in writer help and model role configuration errors.
* Correct onboarding documentation to reflect the existing environment based default role registry rather than claiming automatic configuration file loading.
* Add isolated process regressions for current, legacy, and installed discovery, absent packages, missing bindings, and public writer help. Discovery never executes a provider.
* Use SPDX MIT license metadata and a compatible setuptools floor so fresh wheel builds avoid deprecated license table warnings.
* Declare httpx2 as a development dependency for the current Starlette TestClient, avoiding its deprecated httpx fallback in fresh native test environments.
