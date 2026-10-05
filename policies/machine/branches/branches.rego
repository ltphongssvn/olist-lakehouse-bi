# policies/machine/branches/branches.rego

# METADATA
# title: Branch policy
# description: This checkout's long-lived branches match their remote.
# entrypoint: true
package machine.branches

# THE INVARIANT (D.10): a long-lived branch is never behind its remote, never
# ahead of it, never diverged from it. sync repairs behind by fast-forward and
# reports the rest, then asks this.
#
# NAMESPACED under machine. because it judges THIS CHECKOUT, not the repository:
# CI has no local main at all. evaluate_policies excludes machine.*, so the
# pre-push gate never refuses to push the fix that brings a branch current.

import rego.v1

observed if input.repository_state.branches

long_lived contains branch if {
	some branch in input.repository_state.branches
	branch.name in input.repository_state.long_lived
}

# METADATA
# title: The checkout's branches must be observed
# description: A state nobody gathered cannot show its long-lived branches are current.
# custom:
#   code: ERR_BRANCH_UNOBSERVED
deny contains denial if {
	not observed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no repository state was observed, so no branch can be judged current",
	}
}

# METADATA
# title: No long-lived branch is behind
# description: Behind its remote, a long-lived branch is a stale base for new work.
# custom:
#   code: ERR_BRANCH_BEHIND
deny contains denial if {
	some branch in long_lived
	branch.position == "behind"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is behind its remote; run mise run sync", [branch.name]),
	}
}

# METADATA
# title: No long-lived branch is ahead
# description: Long-lived branches change only by pull request.
# custom:
#   code: ERR_BRANCH_AHEAD
deny contains denial if {
	some branch in long_lived
	branch.position == "ahead"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s holds commits its remote lacks; it changes only by pull request", [branch.name]),
	}
}

# METADATA
# title: No long-lived branch has diverged
# description: A divergence needs a person; nothing here forces one.
# custom:
#   code: ERR_BRANCH_DIVERGED
deny contains denial if {
	some branch in long_lived
	branch.position == "diverged"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s has diverged from its remote; resolve it by hand", [branch.name]),
	}
}
