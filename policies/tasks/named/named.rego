# policies/tasks/named/named.rego

# METADATA
# title: Named-task policy
# description: Every task a tracked message tells the reader to run is a declared task.
# entrypoint: true
package tasks.named

# A remediation naming a task that does not exist fails at the exact moment someone
# follows it. The declared set is mise own resolution, as tasks:list reports it (D.56).

import rego.v1

# METADATA
# title: A named task is declared
# description: The task a message tells the reader to run must be one mise declares.
# custom:
#   code: ERR_TASK_NAMED_UNDECLARED
deny contains denial if {
	some mention in input.named_tasks.mentions
	not mention.task in {name | some name in input.named_tasks.declared}
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s:%d names mise task %s, which is not declared", [mention.path, mention.number, mention.task]),
	}
}

# METADATA
# title: The named-task inventory is present
# description: Without it the rule above judges nothing, and an empty judgement reads as a pass.
# custom:
#   code: ERR_TASK_NAMED_INPUT_MISSING
deny contains denial if {
	not input.named_tasks
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no named_tasks inventory was supplied, so no named task was judged",
	}
}
