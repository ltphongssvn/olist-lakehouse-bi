# NO PACKAGE-SCOPE METADATA HERE, DELIBERATELY.
#
# A package annotation may be declared ONCE per package. nix.rego carries it;
# this file extends the same package.
#
# RISK FACTORS THAT DO NOT FAIL THE CONTRACT.
# Supply-chain guidance draws the line explicitly: "treat the absence of
# provenance as a risk factor, not an automatic failure", while a MISMATCH is a
# security incident. A gate that fails on every substituted binary is one people
# disable, and a disabled gate detects nothing at all.
#
# THE CODE COMES FROM THE ANNOTATION, NOT FROM THE BODY. Each was written twice
# -- once in custom.code, once in the emitted object -- and scripts/nix_policy.py
# derives its rule list from the ANNOTATIONS via `opa inspect -a` while verify()
# reads the emitted bodies. A disagreement would make a rule enumerable but
# unreportable, or reportable but absent from the verdicts.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head.
package machine.nix

import rego.v1

# METADATA
# title: An absent Nix is noted when nothing yet depends on one
# description: A machine with no flake has no Nix requirement to fail.
# custom:
#   code: WARN_NIX_ABSENT_NOT_REQUIRED
#   severity: warning
warnings contains warning if {
	not input.nix_present
	not input.flake_present
	warning := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"nix was not found in any searched directory (%s)",
			[searched_paths],
		),
		"remediation": {
			"description": "Not a failure: no flake.nix exists, so nothing needs Nix yet.",
			"command": "mise run nix:bootstrap",
			"autonomy": "alert",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: Store paths should carry a trusted signature
# description: Absence of provenance is a risk factor, not a failure.
# custom:
#   code: WARN_NIX_STORE_PATH_UNTRUSTED
#   severity: warning
warnings contains warning if {
	input.nix_present
	input.is_untrusted
	warning := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"%s has no trusted signature: neither locally built, content-addressed, nor signed by a trusted key",
			[store_binary],
		),
		"remediation": {
			"description": "Expected for anything substituted from a binary cache.",
			"command": sprintf("nix store verify --sigs-needed 1 %s", [store_binary]),
			"autonomy": "approve",
			"reversible": true,
			"privileged": false,
		},
	}
}

# METADATA
# title: Store verification should complete
# description: A killed probe leaves integrity unknown rather than confirmed.
# custom:
#   code: WARN_NIX_STORE_VERIFY_KILLED
#   severity: warning
warnings contains warning if {
	input.nix_present
	not input.store_verify_ran
	warning := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"`nix store verify` was killed by signal %v, so store integrity is UNKNOWN rather than confirmed",
			[object.get(input, "store_verify_signal", "unknown")],
		),
		"remediation": {
			"description": "Absence of evidence is not evidence of corruption, but silence needs saying.",
			"command": sprintf("nix store verify %s", [store_binary]),
			"autonomy": "approve",
			"reversible": true,
			"privileged": false,
		},
	}
}

# METADATA
# title: The platform must be one this toolchain supports
# description: An unrecognised system double means every platform-specific rule is guessing.
# custom:
#   code: WARN_NIX_UNKNOWN_PLATFORM
#   severity: warning
warnings contains warning if {
	not input.system in supported_systems
	warning := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"system %q is not one this toolchain builds for: every platform-specific judgement is a guess",
			[input.system],
		),
		"remediation": {
			"description": "The flake declares three systems. Elsewhere these rules may be wrong, not merely unverified.",
			"command": null,
			"autonomy": "alert",
			"reversible": false,
			"privileged": false,
		},
	}
}

# METADATA
# title: A build group indicates a multi-user install
# description: Single-user installations legitimately have none.
# custom:
#   code: WARN_NIX_BUILD_GROUP_MISSING
#   severity: warning
warnings contains warning if {
	# GUARDED, because a machine with no Nix has no build group to be missing.
	# The first pass guarded the problems and missed three warnings, which then
	# reported defects that cannot exist -- a wall of findings all restating one
	# fact, surviving where the test only looked at problems.
	input.nix_present

	# BOTH DARWIN DOUBLES, DELIBERATELY, EVEN THOUGH ONE IS UNSUPPORTED.
	# This rule asks "is this macOS", and an Intel Mac still is -- it has a
	# nixbld group and a store of the same shape. That it can no longer get a
	# toolchain is a different fact, reported by WARN_NIX_UNKNOWN_PLATFORM.
	# Conflating the two would stop this rule judging a real machine shape.
	input.system in ["aarch64-darwin", "x86_64-darwin"]
	input.build_group_id == null
	warning := {
		"code": rego.metadata.rule().custom.code,
		"message": "the nixbld group does not exist",
		"remediation": {
			"description": "Single-user installs have no build group; builds run as the calling user. Supported, so this warns.",
			"command": null,
			"autonomy": "alert",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: Store ownership and mode should match the documented values
# description: Not writable, so the trust model holds; single-user installs differ.
# custom:
#   code: WARN_NIX_STORE_PERMISSIONS
#   severity: warning
warnings contains unexpected_permissions if {
	input.nix_present
	not input.store_writable_by_me
	input.store_owner != "root"
}

warnings contains unexpected_permissions if {
	input.nix_present
	not input.store_writable_by_me

	# 1021 is 0o1775: Rego has no octal literal, so the decimal is written out.
	input.store_mode != 1021
}

# NOT rego.metadata.rule() HERE, AND THE REASON IS STRUCTURAL.
#
# This value is shared by TWO rule bodies above, so it is defined outside both
# -- and rego.metadata.rule() reads the annotation of the rule it is evaluated
# in, which for a standalone definition is this one, not either caller. The code
# is therefore written literally, and the annotation above the first body
# declares it for `opa inspect -a`.
#
# The duplication is real and narrow. A test asserts the two agree rather than
# trusting them to.
unexpected_permissions := {
	"code": "WARN_NIX_STORE_PERMISSIONS",
	"message": sprintf(
		"%s is owner=%s mode=%o, expected root and 1775",
		[input.store_path, input.store_owner, input.store_mode],
	),
	"remediation": {
		"description": "Not writable by this user, so the trust model holds. Single-user installs differ.",
		"command": sprintf(
			"sudo chown root:nixbld %s && sudo chmod 1775 %s",
			[input.store_path, input.store_path],
		),
		"autonomy": "approve",
		"reversible": true,
		"privileged": true,
	},
}
