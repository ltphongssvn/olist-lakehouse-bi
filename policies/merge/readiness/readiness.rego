# policies/merge/readiness/readiness.rego

# METADATA
# title: Merge readiness policy
# description: Whether a pull request may merge now, from GitHub's own verdict and every check.
# entrypoint: true
package merge.readiness

# Every visible check being green is not a verdict: a finished check already on the
# head commit answered while the PR's required run had not registered. GitHub
# reports BLOCKED while required checks are queued or running, and UNKNOWN while it
# is still computing, so those states wait. Every rule needs a pull_request input,
# so the gate's own payload leaves this package quiet.

import rego.v1

undecided_states := {"BLOCKED", "UNKNOWN"}

passing := {"SUCCESS", "NEUTRAL", "SKIPPED"}

failed contains name if {
	some check in input.pull_request.checks
	check.conclusion != null
	not check.conclusion in passing
	name := check.name
}

pending contains name if {
	some check in input.pull_request.checks
	check.conclusion == null
	name := check.name
}

waiting if count(pending) > 0

waiting if input.pull_request.merge_state in undecided_states

waiting if count(input.pull_request.checks) == 0

decision := "refuse" if count(deny) > 0

decision := "wait" if {
	count(deny) == 0
	waiting
}

decision := "merge" if {
	input.pull_request
	count(deny) == 0
	not waiting
}

# METADATA
# title: A failed check refuses the merge, by name
# description: A concluded check outside SUCCESS, NEUTRAL and SKIPPED is a verdict, not a wait.
# custom:
#   code: ERR_MERGE_CHECK_FAILED
deny contains denial if {
	some name in failed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s concluded unacceptably", [name]),
	}
}

# METADATA
# title: A conflicting pull request cannot merge
# description: GitHub spells a merge conflict DIRTY.
# custom:
#   code: ERR_MERGE_CONFLICTING
deny contains denial if {
	input.pull_request.merge_state == "DIRTY"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the pull request conflicts with its base; resolve it, then merge",
	}
}

# METADATA
# title: A pull request behind its base cannot merge
# description: Update the branch from its base first.
# custom:
#   code: ERR_MERGE_BEHIND
deny contains denial if {
	input.pull_request.merge_state == "BEHIND"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the pull request is behind its base; update the branch, then merge",
	}
}

# METADATA
# title: A draft pull request cannot merge
# description: Mark it ready for review first.
# custom:
#   code: ERR_MERGE_DRAFT
deny contains denial if {
	input.pull_request.merge_state == "DRAFT"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the pull request is a draft",
	}
}

# METADATA
# title: An unstable pull request does not merge
# description: A non-passing status GitHub does not require still blocks this repository's merge.
# custom:
#   code: ERR_MERGE_UNSTABLE
deny contains denial if {
	input.pull_request.merge_state == "UNSTABLE"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "GitHub reports a non-passing status on the pull request",
	}
}
