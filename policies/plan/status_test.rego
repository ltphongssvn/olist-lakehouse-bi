package plan_test

import rego.v1

import data.plan

facts := {
	"ref": "origin/develop", "paths": ["a.py"], "tasks": [], "merged_prs": [],
	"tags": [], "proofs": [], "branches_with_work": [], "blind": [],
}

held := {"kind": "path", "path": "a.py"}

missing := {"kind": "path", "path": "absent.py"}

test_a_step_with_every_item_held_is_done if {
	result := plan.status with input as {"plan_facts": {"facts": facts, "steps": [
		{"id": "C.1", "depends_on": [], "done_when": [held]},
	]}}
	result["C.1"].state == "done"
}

test_a_step_with_one_item_missing_is_in_progress if {
	result := plan.status with input as {"plan_facts": {"facts": facts, "steps": [
		{"id": "C.1", "depends_on": [], "done_when": [held, missing]},
	]}}
	result["C.1"].state == "in_progress"
}

test_absent_facts_are_denied if {
	some denial in plan.deny with input as {}
	denial.code == "ERR_PLAN_UNOBSERVED"
}
