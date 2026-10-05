# METADATA
# title: Runtime contract policy tests
# description: Every rule asserted firing and not firing.
package runtime_test

# BOTH DIRECTIONS, EVERY RULE.
# This repo shipped a rule using a negative lookahead, which Go's RE2 omits, so
# it matched NOTHING while 21 tests passed. Only a test asserting the rule FIRES
# exposed it.
#
# FIRING CASES ASSERT A CODE; NON-FIRING CASES ASSERT A COUNT.
#
# A count on a firing case couples the test to every other rule in the package.
# test_denies_a_piped_bare_interpreter is the clearest example: its fixture also
# contains a `databricks api` call, and under a count assertion it was only ever
# one rule away from failing for an unrelated reason.
#
# A code assertion says "this rule fired" and stays true however many others
# also did. A count still belongs on the negative cases, where the claim really
# is "nothing fired at all".

import data.runtime
import rego.v1

# Finds a denial by code, so a test names the rule it is about.
fired(result, code) if {
	some denial in result
	denial.code == code
}

test_denies_a_bare_interpreter if {
	result := runtime.deny with input as {"commands": [{"task": "x", "argv": ["python3", "s.py"]}]}
	fired(result, "ERR_RUNTIME_BARE_INTERPRETER")
}

test_denies_a_piped_bare_interpreter if {
	# The four this policy found that a text-substitution fix had missed: a
	# `| python3 -c` mid-pipeline is not a run-prefix, so replacing
	# `run = "python3 ..."` never saw them.
	result := runtime.deny with input as {"commands": [
		{"task": "x", "argv": ["databricks", "api", "get", "/x"]},
		{"task": "x", "argv": ["python3", "-c", "import sys"]},
	]}
	fired(result, "ERR_RUNTIME_BARE_INTERPRETER")
}

test_denies_mise_exec_python if {
	# The fix someone reaches for on discovering the problem, which is not one:
	# mise does not manage Python here, so it falls through to PATH. Since the
	# toolchain cutover it is worse -- mise manages nothing, so `mise exec`
	# fails outright.
	result := runtime.deny with input as {"commands": [{
		"task": "x",
		"argv": ["mise", "exec", "--", "python3", "y.py"],
	}]}
	fired(result, "ERR_RUNTIME_MISE_EXEC_INTERPRETER")
}

test_denies_an_untokenisable_body if {
	# FAIL CLOSED: a body the lexer could not read is one the policy could not
	# check, and silence there is a blind spot the gate never mentions.
	result := runtime.deny with input as {"commands": [{
		"task": "x",
		"argv": [],
		"unparsed": "echo \"unbalanced",
	}]}
	fired(result, "ERR_RUNTIME_UNPARSEABLE_BODY")
}

test_allows_uv_run_python if {
	result := runtime.deny with input as {"commands": [{
		"task": "x",
		"argv": ["uv", "run", "python", "s.py"],
	}]}
	count(result) == 0
}

test_allows_unrelated_commands if {
	# A rule that fires on everything is as broken as one that never fires; it
	# just fails louder, and it trains people to bypass the gate.
	result := runtime.deny with input as {"commands": [
		{"task": "x", "argv": ["git", "status", "--porcelain"]},
		{"task": "x", "argv": ["databricks", "bundle", "validate"]},
		{"task": "x", "argv": ["echo", "python3 is mentioned but not run"]},
	]}
	count(result) == 0
}

# --- the denial shape ----------------------------------------------------------

# EVERY DENIAL CARRIES BOTH FIELDS. A code with no message is unactionable; a
# message with no code puts callers back to string matching.
test_every_denial_has_a_code_and_a_message if {
	result := runtime.deny with input as {"commands": [{"task": "x", "argv": ["python3", "s.py"]}]}

	every denial in result {
		is_string(denial.code)
		is_string(denial.message)
	}
}
