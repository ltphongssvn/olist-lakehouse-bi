package plan

# EVERY COMMIT NAMES THE PLAN STEPS IT SERVES. The trailers are read by git and
# arrive here as data; this decides. Merges are exempt: GitHub writes them, and
# the pull request's own commits carry the steps.

import rego.v1

commits := input.branch_commits.commits

issued := {id | some id in input.branch_commits.issued}

retired := {id | some id in input.branch_commits.retired}

# METADATA
# title: Commits must be observed
# description: A branch whose commits nobody read cannot show it names its steps.
# custom:
#   code: ERR_TRAILER_UNOBSERVED
deny contains denial if {
	not input.branch_commits.base
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no commits were observed, so no trailer can be judged",
	}
}

# METADATA
# title: Every commit names a plan step
# description: A commit naming no step is work the plan never authorised.
# custom:
#   code: ERR_TRAILER_MISSING
deny contains denial if {
	some commit in commits
	not commit.merge
	count(commit.steps) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s (%s) names no Plan-Step", [commit.sha, commit.subject]),
	}
}

# METADATA
# title: A named step was issued
# description: An id the ledger never issued points at nothing.
# custom:
#   code: ERR_TRAILER_UNKNOWN
deny contains denial if {
	some commit in commits
	some step in commit.steps
	not step in issued
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s names %s, which the id ledger never issued", [commit.sha, step]),
	}
}

# METADATA
# title: A named step is live
# description: A retired id back in use makes every earlier reference to it lie.
# custom:
#   code: ERR_TRAILER_RETIRED
deny contains denial if {
	some commit in commits
	some step in commit.steps
	step in retired
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s names %s, which is retired", [commit.sha, step]),
	}
}
