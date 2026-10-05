# METADATA
# title: Nix installation policy
# description: Judges an observed Nix installation against the project's needs.
# entrypoint: true
package machine.nix

# WHY THESE RULES ARE HERE AND NOT IN PYTHON
# verify() was a sequence of `if` statements appending to a list -- rules that
# could not be enumerated, listed, or tested individually without running the
# whole function. Rego describes "what is true under what conditions, not a
# sequence of imperative steps", which is "significantly easier to audit,
# peer-review, and test than procedural logic embedded inside application code".
#
# THE INPUT is a serialised NixInstallation. The Python side owns OBSERVING the
# machine; this side owns JUDGING what was observed. Nothing here touches the
# host.
#
# THE ENTRYPOINT ANNOTATION ABOVE IS THE PUBLIC CONTRACT, not decoration.
# scripts/nix_policy.py queries data.machine.nix by string, and the annotation
# connects that coupling to this file. IT APPEARS ONCE PER PACKAGE: declaring it
# in all four files produced "package annotation redeclared" three times.
#
# FOUR FILES, ONE PACKAGE. Rego composes a package from every file declaring it,
# so this is a readability split regal asked for twice: `file-length` at 586
# lines against a 500 limit, and `messy-rule` because the problems and warnings
# bodies were interleaved.
#
#   nix.rego        this file: the input contract every rule depends on
#   problems.rego   conditions that make the contract unsatisfied
#   warnings.rego   risk factors that do not fail it
#   helpers.rego    defaulted reads and the total remedy_for function
#
# CODES COME FROM ANNOTATIONS, NOT FROM RULE BODIES.
# rego.metadata.rule() reads a rule's own annotation at evaluation time. That
# matters more here than in the repo policies: scripts/nix_policy.py derives its
# rule list from these annotations via `opa inspect -a`, while verify() reads
# the emitted findings. Two copies of one code could make a rule enumerable but
# unreportable, or reportable but absent from the verdicts.
#
# FAIL CLOSED, WHICH THIS POLICY DID NOT ORIGINALLY DO.
# The tasks policy states the standard: "every deny rule here is written so a
# MISSING input field produces a denial, not an undefined result." Three places
# broke it, and an undefined rule body yields NO FINDING -- silence that reads
# exactly like a pass:
#
#   1. remedy_for was a partial function over six outcomes. ProbeOutcome has
#      seven, so remedy_for("ok") was undefined -- and an undefined value in a
#      `problem :=` assignment kills the ENTIRE rule. A probe failing with an
#      unmapped outcome reported nothing at all.
#   2. count(input.build_users_with_login_shells) and concat(", ",
#      input.searched) assumed their keys exist. A serialisation change dropping
#      either silences the rule rather than failing it.
#   3. Nothing checked that the observation carried the fields the rules read,
#      so a renamed field would disable a rule invisibly.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head.

import rego.v1

# --- The input contract -------------------------------------------------------

# THE FIELDS EVERY JUDGEMENT DEPENDS ON.
#
# A rule reading a missing field goes undefined and produces no finding, which
# is indistinguishable from a rule that examined the machine and approved it.
# Naming the contract here turns that silence into a denial.
required_fields := [
	"nix_present",
	"flake_present",
	"system",
	"searched",
	"store_path",
	"store_exists",
	"store_writable_by_me",
	"store_owner",
	"store_mode",
	"meets_version_floor",
	"evaluate_outcome",
	"flake_outcome",
	"project_flake_checked",
	"project_flake_outcome",
	"is_corrupted",
	"is_untrusted",
	"store_verify_ran",
	"is_uninstallable",
	"build_group_id",
	"build_users_with_login_shells",
]

# THE PLATFORMS THIS TOOLCHAIN CAN ACTUALLY BE BUILT FOR.
#
# THREE, NOT FOUR. nixpkgs dropped x86_64-darwin at 26.11 -- "Nixpkgs 26.11 has
# dropped support for x86_64-darwin", following Apple's announcement that macOS
# 26 is the last version for Intel Macs. The flake tracks unstable and therefore
# cannot build for it at all.
#
# THIS LIST AND flake.nix MUST NAME THE SAME SET. A platform accepted here but
# absent there would pass the contract and then fail at `nix develop`.
supported_systems := ["aarch64-darwin", "aarch64-linux", "x86_64-linux"]

# METADATA
# title: The observation must carry every field the rules read
# description: A missing field silences a rule; this makes it a denial instead.
# custom:
#   code: ERR_NIX_OBSERVATION_INCOMPLETE
#   severity: problem
problems contains problem if {
	some field in required_fields
	not has_field(field)
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"the observation is missing %q, so any rule reading it would be silently skipped",
			[field],
		),
		"remediation": {
			"description": "policy_input() must emit every field in required_fields; a rename disables a rule invisibly.",
			"command": null,
			"autonomy": "alert",
			"reversible": true,
			"privileged": false,
		},
	}
}

# `object.get` WITH A SENTINEL, NOT `input[field]`. A direct index on a missing
# key is undefined, and `not undefined` is true -- which would make this rule
# fire correctly by accident rather than by design.
has_field(field) if {
	object.get(input, field, "<<absent>>") != "<<absent>>"
}
