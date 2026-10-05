# policies/tasks/tasks_test.rego
#
# EVERY DENY RULE GETS A FIRING CASE AND A NON-FIRING CASE.
#
# A rule with only a passing test is indistinguishable from one that cannot
# fire. That matters more here than in application code: this file is pure
# decision logic where every line is a rule, and an uncovered deny is one nobody
# has watched work. The profile rule shipped with a negative lookahead RE2 does
# not support, so it matched nothing -- it looked alive, and only a firing test
# caught it.
#
# FIRING CASES ASSERT A CODE; NON-FIRING CASES ASSERT A COUNT.
#
# Every test used to assert `count(result) == 1`, which coupled it to every
# other rule in the package: a fixture written to exercise the mise-exec rule
# happened to contain `databricks api`, tripped a second rule, and failed for a
# reason unrelated to what it tested.
#
# A code assertion says "this rule fired" and stays true however many others
# also did. A count still belongs on the negative cases, where the claim really
# is "nothing fired at all".

package tasks_test

import data.tasks
import rego.v1

# Finds a denial by code, so a test names the rule it is about.
fired(result, code) if {
	some denial in result
	denial.code == code
}

# --- databricks api confinement ------------------------------------------------

test_denies_raw_api_call_in_an_ordinary_task if {
	result := tasks.deny with input as {
		"tasks": {"deploy": "databricks api post /api/2.0/whatever"},
		"descriptions": {"deploy": "x"},
	}
	fired(result, "ERR_TASK_RAW_API_CALL")
}

test_allows_raw_api_call_in_a_bootstrap_task if {
	result := tasks.deny with input as {
		"tasks": {"bootstrap:identity": "databricks api get /api/2.0/account/scim/v2/Groups"},
		"descriptions": {"bootstrap:identity": "x"},
	}
	count(result) == 0
}

test_allows_raw_api_call_in_an_auth_task if {
	result := tasks.deny with input as {
		"tasks": {"auth:rotate-ci-secret": "databricks api post ... | gh secret set X"},
		"descriptions": {"auth:rotate-ci-secret": "x"},
	}
	count(result) == 0
}

# --- profile naming ------------------------------------------------------------

test_denies_a_named_profile if {
	result := tasks.deny with input as {
		"tasks": {"login": "databricks auth login --profile cscie103"},
		"descriptions": {"login": "x"},
	}
	fired(result, "ERR_TASK_NAMED_PROFILE")
}

test_allows_the_default_profile if {
	result := tasks.deny with input as {
		"tasks": {"login": "databricks auth login --profile DEFAULT"},
		"descriptions": {"login": "x"},
	}
	count(result) == 0
}

# --- secret handling -----------------------------------------------------------

test_denies_a_secret_that_is_not_piped_to_the_store if {
	result := tasks.deny with input as {
		"tasks": {"rotate": "databricks api post /credentials/secrets --json '{}'"},
		"descriptions": {"rotate": "x"},
	}
	fired(result, "ERR_TASK_SECRET_RENDERED")
}

test_allows_a_secret_piped_straight_into_gh if {
	result := tasks.deny with input as {
		"tasks": {"auth:rotate": "databricks api post /credentials/secrets | gh secret set X"},
		"descriptions": {"auth:rotate": "x"},
	}
	count(result) == 0
}

# --- curl piped into a shell ---------------------------------------------------

test_denies_piping_a_network_fetch_into_a_shell if {
	result := tasks.deny with input as {
		"tasks": {"setup": "curl -fsSL https://example.com/install | sh"},
		"descriptions": {"setup": "x"},
	}
	fired(result, "ERR_TASK_CURL_PIPE_SHELL")
}

test_allows_it_only_in_nix_bootstrap if {
	result := tasks.deny with input as {
		"tasks": {"nix:bootstrap": "curl -fsSL https://install.determinate.systems/nix | sh -s -- install"},
		"descriptions": {"nix:bootstrap": "x"},
	}
	count(result) == 0
}

# A NAME THAT MERELY CONTAINS "bootstrap" IS NOT THE EXCEPTION. The allowance is
# for one task, not for anything that sounds like it -- otherwise the exception
# widens by accident the first time someone names a task conveniently.
test_denies_a_task_that_only_looks_like_the_exception if {
	result := tasks.deny with input as {
		"tasks": {"bootstrap:everything": "curl -fsSL https://example.com/x | sh"},
		"descriptions": {"bootstrap:everything": "x"},
	}
	fired(result, "ERR_TASK_CURL_PIPE_SHELL")
}

# A curl that does NOT reach a shell is ordinary. The rule must not fire on
# fetching a file, or it becomes a rule people work around.
test_allows_a_curl_that_does_not_reach_a_shell if {
	result := tasks.deny with input as {
		"tasks": {"fetch": "curl -fsSL https://example.com/data.json -o data.json"},
		"descriptions": {"fetch": "x"},
	}
	count(result) == 0
}

# `curl | bash` is the same operation with a different shell name.
test_denies_the_bash_spelling_too if {
	result := tasks.deny with input as {
		"tasks": {"setup": "curl -fsSL https://example.com/install | bash"},
		"descriptions": {"setup": "x"},
	}
	fired(result, "ERR_TASK_CURL_PIPE_SHELL")
}

# A PIPE INTO SOMETHING THAT MERELY CONTAINS "sh" IS NOT THIS OPERATION.
# `| shellcheck` and `| shasum` both end a pipe with those two letters, and a
# rule that fires on them is a rule people route around -- which is how a gate
# dies quietly.
test_allows_a_pipe_into_a_tool_whose_name_contains_sh if {
	result := tasks.deny with input as {
		"tasks": {"lint": "curl -fsSL https://example.com/x.sh | shellcheck -"},
		"descriptions": {"lint": "x"},
	}
	count(result) == 0
}

# --- mise exec -----------------------------------------------------------------

test_denies_mise_exec if {
	result := tasks.deny with input as {
		"tasks": {"diagnose": "mise exec -- databricks auth describe"},
		"descriptions": {"diagnose": "x"},
	}
	fired(result, "ERR_TASK_MISE_EXEC")
}

# `mise run` IS THE REPLACEMENT AND MUST NOT FIRE. A rule that flags the fix as
# well as the defect is one people route around.
test_allows_mise_run if {
	result := tasks.deny with input as {
		"tasks": {"diagnose": "mise run auth:describe"},
		"descriptions": {"diagnose": "x"},
	}
	count(result) == 0
}

# THE STALE REFERENCE THAT PROMPTED THIS RULE WAS MID-PIPELINE, not at the start
# of a line -- and it sat inside `if: failure()`, so it would have been broken
# exactly when needed and silent until then.
#
# THIS TEST IS WHY CODES REPLACED COUNTS. Its first fixture contained
# `databricks api`, which trips a different rule, so `count(result) == 1` failed
# for a reason unrelated to what was being tested.
test_denies_mise_exec_anywhere_in_a_body if {
	result := tasks.deny with input as {
		"tasks": {"rotate": "set -e\nsome-cmd | mise exec -- jq .id"},
		"descriptions": {"rotate": "x"},
	}
	fired(result, "ERR_TASK_MISE_EXEC")
}

# --- descriptions --------------------------------------------------------------

test_denies_an_undescribed_task if {
	result := tasks.deny with input as {
		"tasks": {"mystery": "echo hi"},
		"descriptions": {},
	}
	fired(result, "ERR_TASK_UNDESCRIBED")
}

test_allows_a_described_task if {
	result := tasks.deny with input as {
		"tasks": {"greet": "echo hi"},
		"descriptions": {"greet": "say hello"},
	}
	count(result) == 0
}

# --- fail closed ---------------------------------------------------------------

test_a_missing_descriptions_key_still_denies if {
	# An earlier project shipped the reverse: a missing input field left every
	# deny rule undefined and the decision was ALLOW. Absence must not mean
	# permission.
	result := tasks.deny with input as {"tasks": {"orphan": "echo hi"}}
	fired(result, "ERR_TASK_UNDESCRIBED")
}

# --- the denial shape ----------------------------------------------------------

# EVERY DENIAL CARRIES BOTH FIELDS. A code with no message is unactionable; a
# message with no code puts callers back to string matching.
test_every_denial_has_a_code_and_a_message if {
	result := tasks.deny with input as {
		"tasks": {"deploy": "databricks api post /x"},
		"descriptions": {},
	}

	every denial in result {
		is_string(denial.code)
		is_string(denial.message)
	}
}
