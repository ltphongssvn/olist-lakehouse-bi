# METADATA
# title: Plan policy
# description: Each step's state is decided from facts observed on the integration branch.
# entrypoint: true
package plan

# THE DECISION LIVES HERE, NOT IN PYTHON. scripts/plan_status.py observes what
# holds on a ref; this decides what that makes each step. A step is done when
# every piece of its evidence holds, unknown when the only gap is evidence that
# could not be seen, in progress when some holds or its branch has work, ready
# when everything it depends on is done, and blocked otherwise.
#
# FUNCTIONS TAKE THE FACTS AS AN ARGUMENT, so each is decidable from what it is
# handed rather than from input reached for inside its body.

import rego.v1

steps := input.plan_facts.steps

observed := input.plan_facts.facts

done contains step.id if {
	some step in steps
	complete(step, observed)
}

status[step.id] := entry if {
	some step in steps
	entry := {
		"state": state(step, observed, done),
		"unmet": [describe(evidence, observed) |
			some evidence in step.done_when
			not evidence.kind in observed.blind
			not holds(evidence, observed)
		],
		"blocked_by": [dependency | some dependency in step.depends_on; not dependency in done],
	}
}

holds(evidence, facts) if {
	evidence.kind == "path"
	evidence.path in facts.paths
}

holds(evidence, facts) if {
	evidence.kind == "task"
	evidence.name in facts.tasks
}

holds(evidence, facts) if {
	evidence.kind == "release"
	evidence.tag in facts.tags
}

holds(evidence, facts) if {
	evidence.kind == "pr"
	evidence.number in facts.merged_prs
}

holds(evidence, facts) if {
	evidence.kind == "proof"
	evidence.test in facts.proofs
}

# An item counts as no gap when it holds, or when its kind could not be seen.
satisfied(evidence, facts) if evidence.kind in facts.blind

satisfied(evidence, facts) if holds(evidence, facts)

unseen(step, facts) if {
	some evidence in step.done_when
	evidence.kind in facts.blind
}

complete(step, facts) if {
	not unseen(step, facts)
	every evidence in step.done_when {
		holds(evidence, facts)
	}
}

progressing(step, facts) if {
	some evidence in step.done_when
	not evidence.kind in facts.blind
	holds(evidence, facts)
}

progressing(step, facts) if step.branch in facts.branches_with_work

state(step, facts, finished) := "done" if {
	complete(step, facts)
} else := "unknown" if {
	unseen(step, facts)
	every evidence in step.done_when {
		satisfied(evidence, facts)
	}
} else := "in_progress" if {
	progressing(step, facts)
} else := "ready" if {
	every dependency in step.depends_on {
		dependency in finished
	}
} else := "blocked"

describe(evidence, facts) := sprintf("path %s is not on %s", [evidence.path, facts.ref]) if {
	evidence.kind == "path"
}

describe(evidence, facts) := sprintf("task %s is not in mise.toml on %s", [evidence.name, facts.ref]) if {
	evidence.kind == "task"
}

describe(evidence, _) := sprintf("release %s is not tagged", [evidence.tag]) if {
	evidence.kind == "release"
}

describe(evidence, _) := sprintf("pull request #%d is not merged", [evidence.number]) if {
	evidence.kind == "pr"
}

describe(evidence, facts) := sprintf("test %s is not defined on %s", [evidence.test, facts.ref]) if {
	evidence.kind == "proof"
}

# METADATA
# title: Facts must be observed
# description: A plan judged against nothing cannot be consistent.
# custom:
#   code: ERR_PLAN_UNOBSERVED
deny contains denial if {
	not input.plan_facts.facts.ref
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no plan facts were observed, so no step can be judged",
	}
}

# METADATA
# title: Nothing is done before what it depends on
# description: A done step waiting on an open one means the plan or its evidence is wrong.
# custom:
#   code: ERR_PLAN_DONE_BEFORE_DEPENDENCY
deny contains denial if {
	some step in steps
	complete(step, observed)
	some dependency in step.depends_on
	not dependency in done
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s reads done while %s, which it depends on, does not", [step.id, dependency]),
	}
}
