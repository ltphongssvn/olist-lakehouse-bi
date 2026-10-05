# METADATA
# title: Runtime contract policy
# description: Tasks must not resolve interpreters through PATH.
# entrypoint: true
package runtime

# PATH IS AMBIENT STATE THIS REPO DOES NOT CONTROL.
#
# Fourteen tasks invoked `python3 scripts/...` and every one ran Homebrew's
# 3.14.7 rather than the pinned 3.12.3 -- outside the venv, with none of the
# locked dependencies importable. They passed for weeks because they happened to
# use only the standard library. scripts/environment.py imports pydantic and
# would have failed outright: the boundary built to eliminate ambient state was
# unreachable from the tasks it was built for.
#
# A bare command name is a PATH lookup, and PATH is whatever the shell
# inherited. The same class of exposure is documented for executables generally:
# a 2026 hardening report describes a lookup returning a RELATIVE path when "."
# is on PATH, letting a local attacker place a binary in the working directory
# and have it executed.
#
# THIS MATCHES STRUCTURE, NOT TEXT.
#
# input.commands is produced by tokenising each task body with shlex --
# comments stripped, quoting respected -- so a rule asks whether argv[0] IS an
# interpreter rather than whether the body mentions one. Regexing shell text is
# a documented failure mode for command-allowlist gates specifically: heredoc
# bodies and quoted regions are literal text the shell never executes, and a
# naive pattern fires on them.
#
# It also finds what text substitution cannot. The fix that rewrote
# `run = "python3 ..."` on fourteen tasks missed four `| python3 -c` calls piped
# mid-pipeline; this parser reported them immediately.
#
# DENIALS ARE OBJECTS WITH CODES, AND THE CODE COMES FROM THE ANNOTATION.
#
# A string denial can only be tested by counting results or matching prose, and
# a count couples every test to every other rule. The piped-interpreter test is
# the clearest case: its fixture also contains a `databricks api` call, so under
# a count it was one rule away from failing for an unrelated reason.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head, where the annotation has already closed.

import rego.v1

# uv owns Python here. node, ruby and perl are listed because adding one later
# would reintroduce the same ambient resolution with no rule against it.
bare_interpreters := {"python", "python3", "node", "ruby", "perl"}

# METADATA
# title: Interpreters are not resolved through PATH
# description: A bare command name is whatever the shell happened to inherit.
# custom:
#   code: ERR_RUNTIME_BARE_INTERPRETER
deny contains denial if {
	some invocation in input.commands
	interpreter := invocation.argv[0]
	interpreter in bare_interpreters
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q invokes %q directly, which resolves through PATH. %s",
			[invocation.task, interpreter, "Use `uv run python` so the pinned interpreter runs."],
		),
	}
}

# METADATA
# title: mise exec does not make an interpreter controlled
# description: mise manages no Python here, so it falls through to PATH.
# custom:
#   code: ERR_RUNTIME_MISE_EXEC_INTERPRETER
deny contains denial if {
	# It reads as a controlled invocation and is not one, which makes it exactly
	# the fix someone reaches for on discovering the problem.
	#
	# SINCE THE TOOLCHAIN CUTOVER IT IS WORSE THAN INEFFECTIVE: mise manages no
	# tools at all, so `mise exec` fails outright with "No version is set for
	# shim". policies/tasks denies the construct generally; this rule keeps the
	# interpreter-specific reasoning where a reader of the runtime policy finds
	# it.
	some invocation in input.commands
	invocation.argv[0] == "mise"
	"exec" in invocation.argv
	some argument in invocation.argv
	argument in bare_interpreters
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q uses `mise exec -- %s`, which still resolves through PATH: %s",
			[invocation.task, argument, "mise does not manage Python here. Use `uv run python`."],
		),
	}
}

# METADATA
# title: A body that cannot be tokenised was not checked
# description: Silence about an unreadable body is a blind spot the gate never mentions.
# custom:
#   code: ERR_RUNTIME_UNPARSEABLE_BODY
deny contains denial if {
	# FAIL CLOSED. A parser that silently drops what it cannot read reports
	# clean on the tasks it could not examine.
	some invocation in input.commands
	invocation.unparsed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q has a body that could not be tokenised, so it was not checked: %s",
			[invocation.task, invocation.unparsed],
		),
	}
}
