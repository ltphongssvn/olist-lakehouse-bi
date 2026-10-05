package plan

# THE REQUIREMENT MATRIX, JUDGED IN BOTH DIRECTIONS. A commit on develop that
# names no step and is cited nowhere is work no step authorised. A step that
# reads done with no commit naming it and no historical source is done with no
# record of the work. plan:trace already requires every item to have some
# source, so that is not repeated here.

import rego.v1

matrix := input.requirement_matrix

historical(row) if {
	some source in row.justified_by
	startswith(source, "HISTORY:")
}

historical(row) if {
	some source in row.justified_by
	startswith(source, "RELEASES:")
}

# METADATA
# title: The matrix must be observed
# description: A matrix nobody derived cannot show anything traces.
# custom:
#   code: ERR_MATRIX_UNOBSERVED
deny contains denial if {
	not input.requirement_matrix.ref
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no requirement matrix was derived, so nothing can be shown to trace",
	}
}

# METADATA
# title: Every change traces to a step
# description: A commit naming no step and cited by no history is work nothing authorised.
# custom:
#   code: ERR_MATRIX_COMMIT_UNTRACED
deny contains denial if {
	some commit in matrix.commits
	not commit.merge
	not commit.cited
	count(commit.steps) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s (%s) names no step and no history cites it", [substring(commit.sha, 0, 9), commit.subject]),
	}
}

# METADATA
# title: Every done step traces to its work
# description: Done with no commit naming it and no historical source is done with no record.
# custom:
#   code: ERR_MATRIX_DONE_UNTRACED
deny contains denial if {
	some row in matrix.requirements
	row.state == "done"
	not historical(row)
	count(row.referenced_by) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s reads done, but no commit names it and no history records its work", [row.id]),
	}
}
