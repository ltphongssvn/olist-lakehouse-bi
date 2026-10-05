# METADATA
# title: Merge protocol policy tests
# description: Every rule asserted firing and not firing.
package merge_test

# BOTH DIRECTIONS, EVERY RULE.
# This repo shipped a rule using a negative lookahead, which Go's RE2 omits, so
# it matched NOTHING while 21 tests passed. Only a test asserting the rule FIRES
# exposed it.
#
# FIRING CASES ASSERT A CODE; NON-FIRING CASES ASSERT A COUNT.
#
# A count on a firing case couples the test to every other rule in the package:
# a fixture written for one rule that also trips a second fails for a reason
# unrelated to what it tests. A code assertion says "this rule fired" and stays
# true however many others also did. A count still belongs on the negative
# cases, where the claim really is "nothing fired at all".

import data.merge
import rego.v1

# Finds a denial by code, so a test names the rule it is about.
fired(result, code) if {
	some denial in result
	denial.code == code
}

test_denies_gh_pr_merge_auto if {
	result := merge.deny with input as {"commands": [{
		"task": "release",
		"argv": ["gh", "pr", "merge", "--auto", "--merge"],
	}]}
	fired(result, "ERR_MERGE_AUTO_MERGE")
}

test_denies_a_direct_call_to_the_merge_endpoint if {
	# The endpoint verifies nothing, so a task reaching it directly would merge
	# a red pull request instantly.
	result := merge.deny with input as {"commands": [{
		"task": "shortcut",
		"argv": ["gh", "api", "repos/o/r/pulls/1/merge", "-X", "PUT"],
	}]}
	fired(result, "ERR_MERGE_DIRECT_ENDPOINT")
}

test_allows_a_plain_merge_without_auto if {
	# `gh pr merge` on its own is a human action, not the broken async path.
	result := merge.deny with input as {"commands": [{
		"task": "manual",
		"argv": ["gh", "pr", "merge", "--merge"],
	}]}
	count(result) == 0
}

test_allows_unrelated_gh_api_calls if {
	# A rule that fires on everything is as broken as one that never fires; it
	# just fails louder, and it trains people to bypass the gate.
	result := merge.deny with input as {"commands": [
		{"task": "repo:configure", "argv": ["gh", "api", "repos/o/r/rulesets"]},
		{"task": "pr-status", "argv": ["gh", "pr", "view", "--json", "state"]},
		{"task": "sync", "argv": ["git", "fetch", "origin", "--prune"]},
	]}
	count(result) == 0
}

test_allows_the_verifying_script if {
	# scripts/pr.py is the sanctioned path. Tasks invoke IT, not gh directly,
	# so the policy never sees the endpoint call at all.
	result := merge.deny with input as {"commands": [{
		"task": "pr",
		"argv": ["uv", "run", "python", "scripts/pr.py"],
	}]}
	count(result) == 0
}

# --- the denial shape ----------------------------------------------------------

# EVERY DENIAL CARRIES BOTH FIELDS. A code with no message is unactionable; a
# message with no code puts callers back to string matching.
test_every_denial_has_a_code_and_a_message if {
	result := merge.deny with input as {"commands": [{
		"task": "release",
		"argv": ["gh", "pr", "merge", "--auto"],
	}]}

	every denial in result {
		is_string(denial.code)
		is_string(denial.message)
	}
}
