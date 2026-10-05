# Tests for the Nix installation policy.
#
# EVERY RULE IS ASSERTED BOTH FIRING AND NOT FIRING. A rule seen only passing is
# indistinguishable from one that cannot fire -- this repository has shipped
# exactly that mistake before.
package nix_test

import data.machine.nix
import rego.v1

# A machine that satisfies everything. Each test overrides one field, so a
# failure names the rule rather than the fixture.
healthy := {
	# A machine WITH nix, in a repository that does not yet require one. Every
	# rule guards on nix_present, because an absent machine would otherwise fire
	# all of them at once and say the same thing twelve ways.
	"nix_present": true,
	"flake_present": false,
	"system": "aarch64-darwin",
	"project_flake_checked": false,
	"project_flake_outcome": "ok",
	"project_flake_error": "",
	"searched": ["/nix/var/nix/profiles/default/bin"],
	"store_path": "/nix/store",
	"store_exists": true,
	"store_writable_by_me": false,
	"store_owner": "root",
	"store_mode": 1021,
	"binary": "/nix/store/abc-nix/bin/nix",
	"semantic_version": "2.35.2",
	"minimum_version": "2.18",
	"meets_version_floor": true,
	"evaluate_outcome": "ok",
	"evaluate_error": "",
	"flake_outcome": "ok",
	"flake_error": "",
	"is_corrupted": false,
	"is_untrusted": false,
	"store_verify_ran": true,
	"store_verify_signal": null,
	"is_uninstallable": true,
	"receipt_is_valid": true,
	"uninstaller_exists": true,
	"build_group_id": 350,
	"build_users_with_login_shells": [],
}

# --- this repository's own flake ------------------------------------------------

test_a_broken_project_flake_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {
		"project_flake_checked": true,
		"project_flake_outcome": "unknown_failure",
		"project_flake_error": "error: attribute 'outputs' missing",
	})
	problem.code == "ERR_NIX_PROJECT_FLAKE_BROKEN"
}

test_a_working_project_flake_is_no_problem if {
	codes := {f.code | some f in nix.problems} with input as object.union(healthy, {
		"project_flake_checked": true,
		"project_flake_outcome": "ok",
	})

	not "ERR_NIX_PROJECT_FLAKE_BROKEN" in codes
}

# A PROBE THAT COULD NOT RUN IS NOT A PROBE THAT PASSED.
#
# The default outcome is "ok", so without the checked flag a repository with no
# flake would report a passing flake check it never performed -- the vacuous
# truth this contract keeps removing.
test_an_unchecked_project_flake_is_not_reported_as_passing if {
	codes := {f.code | some f in nix.problems} with input as object.union(healthy, {
		"project_flake_checked": false,
		"project_flake_outcome": "unknown_failure",
	})

	not "ERR_NIX_PROJECT_FLAKE_BROKEN" in codes
}

test_the_project_flake_error_reaches_the_message if {
	some problem in nix.problems with input as object.union(healthy, {
		"project_flake_checked": true,
		"project_flake_outcome": "unknown_failure",
		"project_flake_error": "error: attribute 'outputs' missing",
	})
	contains(problem.message, "attribute 'outputs' missing")
}

# --- the input contract ---------------------------------------------------------
#
# THE FAIL-CLOSED RULE, AND IT NEEDS TESTING MOST.
# A rule reading a missing field goes UNDEFINED and produces no finding, which
# reads exactly like a machine that was examined and approved. This turns that
# silence into a denial -- and a guard nobody has watched fire is
# indistinguishable from one that cannot.

test_a_complete_observation_reports_no_incompleteness if {
	codes := {p.code | some p in nix.problems} with input as healthy
	not "ERR_NIX_OBSERVATION_INCOMPLETE" in codes
}

test_a_missing_field_is_a_problem_not_silence if {
	# object.remove rather than a hand-written partial fixture: removing from
	# the real one proves the rule catches a field that genuinely was there.
	incomplete := object.remove(healthy, {"store_writable_by_me"})

	some problem in nix.problems with input as incomplete
	problem.code == "ERR_NIX_OBSERVATION_INCOMPLETE"
}

test_the_missing_field_is_named if {
	# An incompleteness report that does not say WHICH field sends someone
	# reading twenty rules to find out.
	incomplete := object.remove(healthy, {"store_writable_by_me"})

	some problem in nix.problems with input as incomplete
	contains(problem.message, "store_writable_by_me")
}

test_every_required_field_is_checked if {
	# EXHAUSTIVE: removing ANY required field must be caught. A rule that
	# happened to check only the first few would pass the tests above.
	every field in nix.required_fields {
		codes := {p.code | some p in nix.problems} with input as object.remove(healthy, {field})
		"ERR_NIX_OBSERVATION_INCOMPLETE" in codes
	}
}

test_a_false_field_is_present_not_missing if {
	# THE SENTINEL EXISTS FOR THIS. `input[field]` on a key holding false is
	# defined-and-falsy, and a naive presence check written as `not input[field]`
	# would report every false field as absent -- firing on the healthy fixture,
	# where store_writable_by_me is false by design.
	codes := {p.code | some p in nix.problems} with input as healthy
	not "ERR_NIX_OBSERVATION_INCOMPLETE" in codes
}

# --- platform ------------------------------------------------------------------

test_a_supported_platform_warns_about_nothing if {
	codes := {finding.code | some finding in nix.warnings} with input as healthy
	not "WARN_NIX_UNKNOWN_PLATFORM" in codes
}

test_an_unrecognised_platform_warns if {
	# Every platform-specific rule below is a guess on a system Nix does not
	# build for, and saying so is more honest than judging silently.
	some warning in nix.warnings with input as object.union(healthy, {"system": "riscv64-linux"})
	warning.code == "WARN_NIX_UNKNOWN_PLATFORM"
}

# THREE, NOT FOUR, AND THE TEST NAME SAID FOUR.
#
# nixpkgs dropped x86_64-darwin at 26.11 following Apple ending Intel support,
# so the flake cannot build for it and the policy no longer accepts it. This
# test asserted the old set and failed the moment the platform list narrowed --
# which is the lock working: a supported-platform change cannot land quietly.
#
# ASSERTED AGAINST supported_systems ITSELF, so the list and the test cannot
# drift again. A hardcoded copy here would need remembering; this one cannot.
test_every_supported_double_is_accepted if {
	every double in nix.supported_systems {
		codes := {f.code | some f in nix.warnings} with input as object.union(
			healthy,
			{"system": double},
		)
		not "WARN_NIX_UNKNOWN_PLATFORM" in codes
	}
}

# THE ASSUMPTION THAT WAS SILENTLY WRONG OFF DARWIN.
test_a_missing_build_group_warns_on_darwin if {
	some warning in nix.warnings with input as object.union(healthy, {"build_group_id": null})
	warning.code == "WARN_NIX_BUILD_GROUP_MISSING"
}

test_a_missing_build_group_does_not_warn_on_linux if {
	# A single-user Linux install legitimately has no nixbld group. The rule
	# warned about it anyway, because it was written from one macOS machine.
	codes := {finding.code | some finding in nix.warnings} with input as object.union(
		healthy,
		{"system": "x86_64-linux", "build_group_id": null},
	)

	not "WARN_NIX_BUILD_GROUP_MISSING" in codes
}

# --- an absent nix ------------------------------------------------------------
#
# THE CASE THAT USED TO BE A PYTHON BRANCH. run() decided it with an `if` that
# no rule covered and no verdict reported. It belongs here because the answer
# depends on whether the repository needs Nix, which is a policy question.

absent := object.union(healthy, {"nix_present": false})

test_an_absent_nix_with_no_flake_is_a_warning_not_a_problem if {
	some warning in nix.warnings with input as absent
	warning.code == "WARN_NIX_ABSENT_NOT_REQUIRED"
}

test_an_absent_nix_with_no_flake_produces_no_problem if {
	count(nix.problems) == 0 with input as absent
}

test_an_absent_nix_with_a_flake_is_a_problem if {
	some problem in nix.problems with input as object.union(absent, {"flake_present": true})
	problem.code == "ERR_NIX_ABSENT"
}

test_an_absent_nix_does_not_fire_every_other_rule if {
	# WITHOUT THE nix_present GUARDS this produced a wall of findings -- no
	# store, no version, cannot evaluate -- every one restating a single fact.
	codes := {finding.code | some finding in nix.problems} with input as absent
	count(codes) == 0
}

# THE TEST ABOVE CHECKED ONLY PROBLEMS, AND THAT GAP WAS REAL.
#
# Three WARNING bodies went unguarded and fired on a machine with no Nix --
# reporting a missing build group and unexpected store permissions on a host
# that has neither a build group nor a store. The problems were clean, so this
# passed while the output was wrong.
#
# A rule about a machine with Nix must not speak about a machine without one,
# whichever collection it lands in.
test_an_absent_nix_produces_exactly_one_warning if {
	codes := {finding.code | some finding in nix.warnings} with input as absent

	codes == {"WARN_NIX_ABSENT_NOT_REQUIRED"}
}

test_an_absent_nix_reports_where_it_looked if {
	some warning in nix.warnings with input as absent
	contains(warning.message, "/nix/var/nix/profiles/default/bin")
}

test_a_healthy_machine_has_no_problems if {
	count(nix.problems) == 0 with input as healthy
}

test_a_healthy_machine_has_no_warnings if {
	count(nix.warnings) == 0 with input as healthy
}

test_an_unmounted_store_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {"store_exists": false})
	problem.code == "ERR_NIX_STORE_NOT_MOUNTED"
}

test_a_version_below_the_floor_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {"meets_version_floor": false})
	problem.code == "ERR_NIX_VERSION_BELOW_FLOOR"
}

# THE RULE THAT INVALIDATES EVERY OTHER TRUST DECISION.
test_a_writable_store_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {"store_writable_by_me": true})
	problem.code == "ERR_NIX_STORE_WRITABLE"
}

test_a_failing_eval_is_a_problem if {
	some problem in nix.problems with input as object.union(
		healthy,
		{"evaluate_outcome": "feature_disabled"},
	)
	problem.code == "ERR_NIX_CANNOT_EVALUATE"
}

# THE REMEDY MUST MATCH THE CAUSE. Blaming flake support for a dead daemon is
# the misattribution these outcomes replaced.
test_a_dead_daemon_gets_the_daemon_remedy if {
	some problem in nix.problems with input as object.union(
		healthy,
		{"flake_outcome": "daemon_unreachable"},
	)
	problem.code == "ERR_NIX_CANNOT_EVALUATE_FLAKE"
	contains(problem.remediation.description, "daemon")
}

test_an_unknown_failure_offers_no_remedy if {
	some problem in nix.problems with input as object.union(
		healthy,
		{"flake_outcome": "unknown_failure"},
	)
	contains(problem.remediation.description, "No specific remedy")
}

test_a_corrupted_store_path_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {"is_corrupted": true})
	problem.code == "ERR_NIX_STORE_PATH_CORRUPTED"
}

test_an_uninstallable_machine_is_a_problem if {
	some problem in nix.problems with input as object.union(healthy, {"is_uninstallable": false})
	problem.code == "ERR_NIX_NO_RECEIPT"
}

test_a_build_user_with_a_login_shell_is_a_problem if {
	some problem in nix.problems with input as object.union(
		healthy,
		{"build_users_with_login_shells": ["_nixbld7"]},
	)
	problem.code == "ERR_NIX_BUILD_USER_LOGIN_SHELL"
}

# THE DISTINCTION THE POLICY EXISTS TO MAKE: an untrusted signature is a risk
# factor, not a failure. Refusing it would fail every machine that did not build
# its own toolchain.
test_an_untrusted_signature_is_a_warning_not_a_problem if {
	some warning in nix.warnings with input as object.union(healthy, {"is_untrusted": true})
	warning.code == "WARN_NIX_STORE_PATH_UNTRUSTED"
}

# THE OTHER HALF, in its own rule: a non-loop expression inside a `some ... in`
# loop is re-evaluated per iteration, which regal flags as a performance issue.
test_is_untrusted_produces_no_problem if {
	count(nix.problems) == 0 with input as object.union(healthy, {"is_untrusted": true})
}

test_a_killed_verify_is_a_warning if {
	some warning in nix.warnings with input as object.union(
		healthy,
		{"store_verify_ran": false, "store_verify_signal": 9},
	)
	warning.code == "WARN_NIX_STORE_VERIFY_KILLED"
}

test_a_missing_build_group_is_a_warning_not_a_problem if {
	some warning in nix.warnings with input as object.union(healthy, {"build_group_id": null})
	warning.code == "WARN_NIX_BUILD_GROUP_MISSING"
}

# THE OTHER HALF, in its own rule: a non-loop expression inside a `some ... in`
# loop is re-evaluated per iteration, which regal flags as a performance issue.
test_build_group_id_produces_no_problem if {
	count(nix.problems) == 0 with input as object.union(healthy, {"build_group_id": null})
}

test_unexpected_but_safe_permissions_warn if {
	some warning in nix.warnings with input as object.union(healthy, {"store_owner": "someone"})
	warning.code == "WARN_NIX_STORE_PERMISSIONS"
}

# A WRITABLE STORE IS A PROBLEM, NOT MERELY UNEXPECTED PERMISSIONS. The two
# rules must not collapse into one another.
test_a_writable_store_does_not_merely_warn if {
	problems := nix.problems with input as object.union(
		healthy,
		{"store_writable_by_me": true, "store_owner": "someone"},
	)
	count(problems) > 0
}

# --- the one literal code ------------------------------------------------------

# unexpected_permissions IS DEFINED OUTSIDE ITS RULE BODIES, so it cannot read
# its own annotation: rego.metadata.rule() returns the annotation of the rule it
# is evaluated in, and for a standalone definition that is itself, not either of
# the two `warnings contains` bodies that reference it.
#
# Its code is therefore written literally, which is the one place in this policy
# where a code exists twice -- once in the annotation `opa inspect -a` reads,
# once in the emitted object. This asserts they agree rather than trusting them
# to, because a disagreement would make the rule enumerable but unreportable.
test_the_permissions_code_matches_its_annotation if {
	warning := nix.unexpected_permissions with input as object.union(
		healthy,
		{"store_owner": "someone"},
	)

	warning.code == "WARN_NIX_STORE_PERMISSIONS"
}

test_the_permissions_rule_is_declared_with_that_code if {
	# The other half: the ANNOTATION must carry it too. Read from the emitted
	# warning set on a machine that trips the rule, which is the path
	# scripts/nix_policy.py takes.
	codes := {w.code | some w in nix.warnings} with input as object.union(
		healthy,
		{"store_owner": "someone"},
	)

	"WARN_NIX_STORE_PERMISSIONS" in codes
}
