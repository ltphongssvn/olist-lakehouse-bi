# NO PACKAGE-SCOPE METADATA HERE, DELIBERATELY.
#
# A package annotation may be declared ONCE per package. Giving all four files
# one produced "package annotation redeclared" three times. nix.rego carries it
# because that is the entrypoint scripts/nix_policy.py queries; this file
# extends the same package and needs no second declaration.
#
# CONDITIONS THAT MAKE THE CONTRACT UNSATISFIED. A problem sets satisfied=false
# and exit code 1; a warning does not. The split is the 2026 supply-chain line:
# "treat the absence of provenance as a risk factor, not an automatic failure",
# while a MISMATCH is a security incident.
package machine.nix

# EVERY RULE PRODUCES A FULL PROBLEM OBJECT, not a bare string. A caller
# branches on `code`, reads `message`, and acts on `remediation` -- the same
# shape the Python ContractProblem carries, because it becomes one.
#
# THE CODE COMES FROM THE ANNOTATION, NOT FROM THE BODY.
#
# Each code was written twice -- once in custom.code and once in the emitted
# object -- which is two copies of one fact. That mattered more here than
# anywhere: scripts/nix_policy.py derives its rule list by reading these
# annotations with `opa inspect -a`, while verify() reads the emitted bodies. A
# disagreement between them would make a rule enumerable but unreportable, or
# reportable but absent from the verdicts.
#
# rego.metadata.rule() reads a rule's own annotation at evaluation time, so
# there is one source and the two views cannot diverge.
#
# EVERY OPTIONAL READ GOES THROUGH object.get WITH A DEFAULT. A direct index on
# a missing key is undefined, and an undefined value anywhere in the assignment
# kills the whole rule -- reporting nothing where it should report a finding.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head.

import rego.v1

# METADATA
# title: Nix must be installed when this project needs it
# description: Absent Nix is only a problem once a flake makes it required.
# custom:
#   code: ERR_NIX_ABSENT
#   severity: problem
problems contains problem if {
	not input.nix_present
	input.flake_present
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"nix was not found in any searched directory (%s), and flake.nix requires it",
			[searched_paths],
		),
		"remediation": {
			"description": "This project declares a flake, so it cannot be built without Nix.",
			"command": "mise run nix:bootstrap",
			"autonomy": "approve",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: The Nix store must be mounted
# description: Everything else is meaningless if /nix/store is absent.
# custom:
#   code: ERR_NIX_STORE_NOT_MOUNTED
#   severity: problem
problems contains problem if {
	input.nix_present
	not input.store_exists
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s does not exist; the store is not mounted", [input.store_path]),
		"remediation": {
			"description": "Volume not mounted. Check /etc/fstab and reboot; no single command remounts it.",
			"command": null,
			"autonomy": "alert",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: Nix must meet the version floor
# description: Below it, behaviour the project relies on is not guaranteed.
# custom:
#   code: ERR_NIX_VERSION_BELOW_FLOOR
#   severity: problem
problems contains problem if {
	input.nix_present
	not input.meets_version_floor
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"nix %s is below the required %s",
			[
				object.get(input, "semantic_version", "(unknown)"),
				object.get(input, "minimum_version", "(unknown)"),
			],
		),
		"remediation": {
			"description": "Upgrade the Nix daemon.",
			"command": "sudo determinate-nixd upgrade",
			"autonomy": "approve",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: The store must not be writable by this user
# description: Every trust decision in this contract rests on it not being.
# custom:
#   code: ERR_NIX_STORE_WRITABLE
#   severity: problem
problems contains problem if {
	# THE STORE BEING WRITABLE INVALIDATES EVERY OTHER TRUST DECISION, so it is
	# a problem rather than a warning: if a user can write to the store,
	# "resolved into the store" proves nothing.
	input.nix_present
	input.store_writable_by_me
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"%s is WRITABLE by the current user (owner=%s, mode=%o)",
			[input.store_path, input.store_owner, input.store_mode],
		),
		"remediation": {
			"description": "A writable store means anything resolving into it proves nothing.",
			"command": sprintf(
				"sudo chown root:nixbld %s && sudo chmod 1775 %s",
				[input.store_path, input.store_path],
			),
			"autonomy": "approve",
			"reversible": true,
			"privileged": true,
		},
	}
}

# METADATA
# title: Nix must evaluate expressions
# description: A Nix that cannot evaluate cannot build anything.
# custom:
#   code: ERR_NIX_CANNOT_EVALUATE
#   severity: problem
problems contains problem if {
	input.nix_present
	input.evaluate_outcome != "ok"
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"`nix eval` fails in a sanitized environment, outcome=%s: %s",
			[input.evaluate_outcome, object.get(input, "evaluate_error", "")],
		),
		"remediation": {
			"description": remedy_for(input.evaluate_outcome),
			"command": null,
			"autonomy": "alert",
			"reversible": true,
			"privileged": true,
		},
	}
}

# METADATA
# title: Nix must evaluate flakes
# description: flake.nix and flake.lock are the toolchain declaration.
# custom:
#   code: ERR_NIX_CANNOT_EVALUATE_FLAKE
#   severity: problem
problems contains problem if {
	input.nix_present
	input.flake_outcome != "ok"
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"a trivial flake could not be evaluated, outcome=%s: %s",
			[input.flake_outcome, object.get(input, "flake_error", "")],
		),
		"remediation": {
			"description": remedy_for(input.flake_outcome),
			"command": null,
			"autonomy": "alert",
			"reversible": true,
			"privileged": true,
		},
	}
}

# METADATA
# title: This repository's own flake must evaluate
# description: The synthetic probe proves the machinery; this proves the project.
# custom:
#   code: ERR_NIX_PROJECT_FLAKE_BROKEN
#   severity: problem
problems contains problem if {
	input.nix_present
	input.project_flake_checked
	input.project_flake_outcome != "ok"
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"this repository's flake.nix could not be evaluated, outcome=%s: %s",
			[input.project_flake_outcome, object.get(input, "project_flake_error", "")],
		),
		"remediation": {
			"description": "Only a synthetic flake was evaluated before, so a broken flake.nix passed.",
			"command": "nix flake metadata .",
			"autonomy": "approve",
			"reversible": true,
			"privileged": false,
		},
	}
}

# METADATA
# title: Store contents must match their recorded hash
# description: A mismatch is a security incident, not a risk factor.
# custom:
#   code: ERR_NIX_STORE_PATH_CORRUPTED
#   severity: problem
problems contains problem if {
	input.nix_present
	input.is_corrupted
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"`nix store verify` reports %s as CORRUPTED: contents do not match the recorded NAR hash",
			[store_binary],
		),
		"remediation": {
			"description": "Repair the store path from a substituter.",
			"command": sprintf("nix store repair %s", [store_binary]),
			"autonomy": "approve",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: The installation must be uninstallable
# description: Both a valid receipt and the installer binary are required.
# custom:
#   code: ERR_NIX_NO_RECEIPT
#   severity: problem
problems contains problem if {
	input.nix_present
	not input.is_uninstallable
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"cannot be uninstalled by the supported route: receipt_valid=%v uninstaller_present=%v",
			[
				object.get(input, "receipt_is_valid", false),
				object.get(input, "uninstaller_exists", false),
			],
		),
		"remediation": {
			"description": "Manual removal edits /etc/fstab and is a documented hazard.",
			"command": null,
			"autonomy": "alert",
			"reversible": false,
			"privileged": true,
		},
	}
}

# METADATA
# title: Build users must not be loggable
# description: A login shell turns a build account into an account.
# custom:
#   code: ERR_NIX_BUILD_USER_LOGIN_SHELL
#   severity: problem
problems contains problem if {
	# A BUILD USER WITH A LOGIN SHELL IS AN ACCOUNT SOMEONE CAN LOG IN AS, which
	# is what /sbin/nologin exists to prevent.
	input.nix_present
	count(login_shell_users) > 0
	problem := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"build users have real login shells: %v",
			[concat(", ", login_shell_users)],
		),
		"remediation": {
			"description": "Build users exist solely to run builds. A login shell turns one into an account.",
			"command": "sudo chsh -s /sbin/nologin <user>",
			"autonomy": "approve",
			"reversible": true,
			"privileged": true,
		},
	}
}
