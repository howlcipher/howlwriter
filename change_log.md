# Change Log

## Unreleased

* Discover explicitly selected HowlPlane source checkouts using the current src/howlplane/control_plane layout while preserving installed packages and the legacy source layout.
* Show concrete environment binding and source checkout instructions in writer help and model role configuration errors.
* Correct onboarding documentation to reflect the existing environment based default role registry rather than claiming automatic configuration file loading.
* Add isolated process regressions for current, legacy, and installed discovery, absent packages, missing bindings, and public writer help. Discovery never executes a provider.
* Use SPDX MIT license metadata and a compatible setuptools floor so fresh wheel builds avoid deprecated license table warnings.
* Declare httpx2 as a development dependency for the current Starlette TestClient, avoiding its deprecated httpx fallback in fresh native test environments.
