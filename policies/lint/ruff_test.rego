package lint_test

import rego.v1

import data.lint

test_a_cache_free_check_is_allowed if {
	count(lint.deny) == 0 with input as {"invocations": {"invocations": [
		{"source": "task:lint", "argv": ["ruff", "check", "--no-cache", "."]},
	]}}
}

test_a_cached_check_is_denied if {
	some denial in lint.deny with input as {"invocations": {"invocations": [
		{"source": "task:lint", "argv": ["ruff", "check", "."]},
	]}}
	denial.code == "ERR_RUFF_CACHED"
}

test_no_check_is_denied if {
	some denial in lint.deny with input as {}
	denial.code == "ERR_RUFF_UNOBSERVED"
}
