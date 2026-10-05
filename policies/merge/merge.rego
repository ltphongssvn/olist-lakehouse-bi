# METADATA
# title: Merge protocol policy
# description: Merges go through the verifying path, never around it.
# entrypoint: true
package merge

# A TEST CHECKS THE CODE THAT EXISTS; A POLICY CHECKS THAT IT IS STILL THE CODE
# WE CHOSE.
#
# tests/test_pr.py proves verify_checks refuses an empty list, a running check
# and a failure. It cannot prevent someone adding a task tomorrow that merges
# without calling it at all.
#
# Both rules below encode findings that cost real time.
#
# DENIALS ARE OBJECTS WITH CODES, AND THE CODE COMES FROM THE ANNOTATION.
#
# A string denial can only be tested by counting results or matching prose, and
# a count couples every test to every other rule in the package. Writing the
# code in both the annotation and the body would be two copies of one fact;
# rego.metadata.rule() reads the rule's own annotation at evaluation time.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head, where the annotation has already closed.

import rego.v1

# METADATA
# title: Auto-merge is broken for this purpose
# description: It cannot be enabled until every requirement is already met.
# custom:
#   code: ERR_MERGE_AUTO_MERGE
deny contains denial if {
	# GitHub changed it on 25 March 2026, undocumented: auto-merge returns HTTP
	# 422 unless the pull request already satisfies everything, which leaves it
	# useful only where it is unnecessary. The release hit exactly this --
	# "Required status check 'quality gate' is queued" -- and the pull request
	# sat green and unmerged while the task reported failure.
	#
	# It is also the obvious thing to reach for on reading the merge code, which
	# is why a rule is worth more than a comment.
	some invocation in input.commands
	invocation.argv[0] == "gh"
	"merge" in invocation.argv
	"--auto" in invocation.argv
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q uses `gh pr merge --auto`. Auto-merge cannot be enabled %s",
			[invocation.task, "before checks pass (HTTP 422 since 2026-03-25); use scripts/pr.py."],
		),
	}
}

# METADATA
# title: The merge endpoint verifies nothing
# description: Calling it directly would merge a red pull request instantly.
# custom:
#   code: ERR_MERGE_DIRECT_ENDPOINT
deny contains denial if {
	# It "doesn't care about failing PR checks". scripts/pr.py wraps it with
	# verify_checks, which refuses an empty rollup, a running check and any
	# non-passing conclusion. The endpoint is allowed there and nowhere else.
	some invocation in input.commands
	invocation.argv[0] == "gh"
	"api" in invocation.argv
	some argument in invocation.argv
	endswith(argument, "/merge")
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"task %q calls the merge endpoint directly. It verifies nothing, %s",
			[invocation.task, "so it must go through scripts/pr.py which checks first."],
		),
	}
}
