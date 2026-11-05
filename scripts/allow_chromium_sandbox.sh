#!/usr/bin/env bash
# Lets Playwright's Chromium start its own sandbox on Ubuntu 23.10+ (GitHub's ubuntu-24.04 runners included).
#
# Ubuntu blocks unprivileged user namespaces unless an AppArmor profile allows them for the binary. Google Chrome
# ships such a profile; Playwright's builds don't, so their sandbox fails to start. This adds one for the Playwright
# browsers only: the restriction stays in place for everything else on the machine, and the sandbox stays on.
#
#   scripts/allow_chromium_sandbox.sh   (after `playwright install`; needs sudo)
set -euo pipefail

restriction=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
if [[ ! -r "$restriction" || "$(cat "$restriction")" != "1" ]]; then
  echo "Unprivileged user namespaces aren't restricted here; nothing to do."
  exit 0
fi

browsers="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
profile=/etc/apparmor.d/playwright-chromium

sudo tee "$profile" >/dev/null <<PROFILE
abi <abi/4.0>,
include <tunables/global>

profile playwright-chromium ${browsers}/{chromium,chromium_headless_shell}-*/*/{chrome,chrome-headless-shell} flags=(unconfined) {
  userns,

  include if exists <local/playwright-chromium>
}
PROFILE

sudo apparmor_parser --replace "$profile"
echo "AppArmor profile loaded for the Playwright browsers under $browsers."
