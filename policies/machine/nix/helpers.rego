# NO PACKAGE-SCOPE METADATA HERE, DELIBERATELY.
#
# A package annotation may be declared ONCE per package. nix.rego carries it
# because that is the entrypoint scripts/nix_policy.py queries; this file
# extends the same package.
#
# DEFAULTED READS AND THE TOTAL remedy_for FUNCTION. Everything here exists to
# keep a rule from going UNDEFINED, because an undefined rule body produces no
# finding -- silence indistinguishable from approval.
package machine.nix

import rego.v1

# DEFAULTED READS, so a rule fails LOUDLY on a missing field rather than going
# undefined and producing no finding at all.
#
# The fields themselves are separately required by nix.rego's
# ERR_NIX_OBSERVATION_INCOMPLETE, so absence is REPORTED as well as survived --
# these defaults keep one missing key from silencing every other rule while that
# report is being produced.
searched_paths := concat(", ", object.get(input, "searched", []))

login_shell_users := object.get(input, "build_users_with_login_shells", [])

store_binary := object.get(input, "binary", "(unknown)")

# NAMED REMEDIES PER OUTCOME, so an unrecognised failure gets an honest
# "no specific remedy" rather than the nearest plausible guess.
#
# PATTERN MATCHING IN THE HEAD, which regal prefers over `if outcome == "..."`.
#
# TOTAL, NOT PARTIAL, AND THAT IS THE FAIL-CLOSED FIX.
# This was six definitions with no fallback. ProbeOutcome has seven members, so
# remedy_for("ok") was undefined -- and an undefined value inside a `problem :=`
# assignment kills the ENTIRE rule. A probe failing with an outcome nobody had
# mapped would have been reported as nothing at all, which is the exact failure
# this policy exists to prevent. `default` makes every input answerable.
default remedy_for(_) := "No mapped guidance for this outcome; guessing would be worse."

remedy_for("feature_disabled") := "Add `experimental-features = nix-command flakes` to nix.conf."

remedy_for("daemon_unreachable") := "Start the nix daemon; the store socket is not answering."

remedy_for("disk_full") := "Free space, then re-run. `nix store gc` reclaims unreferenced paths."

remedy_for("permission_denied") := "Check ownership of /nix and the daemon socket."

remedy_for("read_only_store") := "Remount the Nix Store volume; the installation cannot write."

remedy_for("unknown_failure") := "No specific remedy: the error was not recognised."
