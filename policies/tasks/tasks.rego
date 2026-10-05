# METADATA
# title: Task coverage policy
# description: Every project operation is a task or a committed script.
# entrypoint: true
package tasks

# EVERY PROJECT OPERATION IS A TASK OR A COMMITTED SCRIPT.
#
# A one-off CLI invocation is behavior that exists in one person's shell
# history: untested, undiscoverable, and impossible to change deliberately. This
# repo has the evidence -- a service principal was assigned to the workspace and
# added to a group by hand, and neither appeared in bootstrap_identity.py, so a
# rebuilt workspace would have produced a principal that could not log in and
# could read nothing. The script claimed coverage it did not deliver.
#
# WHY THIS IS A POLICY AND NOT A COMMENT: a rule nothing evaluates is a rule
# that decays. The gate already caught missing types and unformatted code; it
# could not catch "this task shells out to an API the repo does not describe".
#
# FAIL CLOSED. Rules are written so a MISSING input field denies rather than
# leaving the decision undefined. Absence must not mean permission.
#
# DENIALS ARE OBJECTS WITH CODES, NOT BARE STRINGS.
#
# They were strings, and a test could then only assert a COUNT or a substring.
# That coupled every test to every other rule: a fixture written to exercise the
# mise-exec rule happened to contain `databricks api`, tripped a second rule,
# and failed on `count(result) == 1` for a reason unrelated to what was tested.
#
# THE CODE COMES FROM THE ANNOTATION, NOT FROM THE BODY.
#
# The first structured version wrote each code twice -- once in custom.code and
# once in the denial object -- which is two copies of one fact and drifts the
# moment someone edits one. rego.metadata.rule() reads a rule's own annotation
# at evaluation time, so the metadata is the single source. It is also what
# `opa inspect -a` enumerates, which is how scripts/nix_policy.py derives its
# rule list rather than maintaining one.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK, AND THIS FILE HAS NOW PROVED
# IT TWICE. The block is parsed as YAML and consumes every following comment
# line until a non-comment line ends it, so prose fails the moment it contains a
# colon. It took the whole policy down once; three rules broke the same way
# converting to metadata-sourced codes. Explanation belongs BELOW the rule head,
# where the annotation has already closed.
#
# THE ENTRYPOINT ANNOTATION ABOVE IS THE PUBLIC CONTRACT, not decoration.
# scripts/evaluate_policies.py queries data.tasks.deny by string.

import rego.v1

# METADATA
# title: Infrastructure work belongs in the bundle
# description: A task calling the Databricks API directly must be bootstrap or auth.
# custom:
#   code: ERR_TASK_RAW_API_CALL
deny contains denial if {
	# Anything else reaching for `databricks api` is doing infrastructure work
	# outside the two places infrastructure is described -- the bundle, or
	# bootstrap_identity.
	some name, body in input.tasks
	contains(body, "databricks api")
	not startswith(name, "bootstrap:")
	not startswith(name, "auth:")
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q calls `databricks api` directly. Infrastructure belongs in the %s",
			[name, "bundle or in bootstrap_identity.py, not an ad hoc API call."],
		),
	}
}

# METADATA
# title: Credentials live in the DEFAULT profile
# description: A named profile reintroduces the which-environment-am-I-in branch.
# custom:
#   code: ERR_TASK_NAMED_PROFILE
deny contains denial if {
	# NO NEGATIVE LOOKAHEAD. OPA uses Go's RE2, which deliberately omits
	# lookarounds to preserve its linear-time guarantee. An earlier version
	# used a negative lookahead and therefore matched NOTHING -- a dead rule
	# that looked alive. Only the firing test caught it, which is the argument
	# for writing both directions.
	some name, body in input.tasks
	matches := regex.find_n(`--profile\s+(\S+)`, body, -1)
	some m in matches
	profile := trim_space(replace(m, "--profile", ""))
	upper(profile) != "DEFAULT"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q names a non-DEFAULT profile. Credentials belong in %s",
			[name, "DEFAULT so local and CI run identical code."],
		),
	}
}

# METADATA
# title: A secret goes API to stdin to the store, never through a variable
# description: A secret that reaches a file or a screen has left the pipe.
# custom:
#   code: ERR_TASK_SECRET_RENDERED
deny contains denial if {
	some name, body in input.tasks
	contains(body, "credentials/secrets")
	not contains(body, "gh secret set")
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q handles an OAuth secret without piping it into %s",
			[name, "`gh secret set`. A rendered secret is a leaked secret."],
		),
	}
}

# METADATA
# title: Only nix:bootstrap may pipe a fetch into a shell
# description: curl into sh runs whatever the server sends, unsigned and unrecorded.
# custom:
#   code: ERR_TASK_CURL_PIPE_SHELL
deny contains denial if {
	# Nix was installed here exactly that way, which is what nix_contract.py
	# exists to have captured after the fact. Permitted in ONE named task, for
	# the same reason `databricks api` is permitted only under bootstrap: and
	# auth: -- the name declares the exception, so it is visible in the task
	# list rather than buried in a body.
	some name, body in input.tasks

	# THE SHELL NAME MUST END THE TOKEN, not merely appear in it. A looser
	# pattern matched `| shellcheck` and `| shasum`, which are ordinary
	# commands. A rule that fires on legitimate work is one people route
	# around, and precision matters as much as recall.
	regex.match(`curl[^|]*\|\s*(ba|z|k|da)?sh(\s|$)`, body)
	name != "nix:bootstrap"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q pipes a network fetch into a shell. %s",
			[name, "Only nix:bootstrap may do this, and only because Nix has no packaged installer."],
		),
	}
}

# METADATA
# title: mise exec resolves through shims that no longer exist
# description: The toolchain cutover removed the tools mise used to manage.
# custom:
#   code: ERR_TASK_MISE_EXEC
deny contains denial if {
	# Nix supplies executables and mise runs tasks. `mise exec` asks mise to
	# resolve a tool it no longer manages, and dies with "No version is set for
	# shim".
	#
	# THIS RULE EXISTS BECAUSE THE CUTOVER LEFT THREE STALE REFERENCES and each
	# was found by accident. One sat inside a failure-only CI step, so it would
	# have been broken exactly when needed and silent until then. Finding the
	# fourth by luck is not a strategy.
	some name, body in input.tasks
	contains(body, "mise exec")
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q uses `mise exec`, which resolves through tool shims the %s",
			[name, "Nix cutover removed. Use `mise run <task>` or call the tool directly."],
		),
	}
}

# METADATA
# title: Every task says what it does
# description: An undescribed task is undiscoverable, which tasks exist to solve.
# custom:
#   code: ERR_TASK_UNDESCRIBED
deny contains denial if {
	some name in object.keys(input.tasks)
	not input.descriptions[name]
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("task %q has no description", [name]),
	}
}
