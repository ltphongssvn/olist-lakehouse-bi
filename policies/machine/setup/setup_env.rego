# policies/machine/setup/setup_env.rego

# METADATA
# title: Setup environment policy
# description: A worktree's setup inherits none of uv's environment-selecting variables.
# entrypoint: true
package machine.setup

# uv locates a project's environment from the working directory; an inherited
# VIRTUAL_ENV or UV_PROJECT_ENVIRONMENT points it at another checkout's instead.
# NAMESPACED under machine. because it judges a process's environment.

import rego.v1

leaked contains name if {
	some name in input.setup_environment.present
	name in input.setup_environment.selecting_variables
}

# METADATA
# title: The setup environment must be observed
# description: An environment nobody looked at cannot show it is clean.
# custom:
#   code: ERR_SETUP_ENV_UNOBSERVED
deny contains denial if {
	not input.setup_environment.selecting_variables[0]
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the setup environment was not observed",
	}
}

# METADATA
# title: Setup inherits no environment-selecting variable
# description: Each one points uv at another checkout's environment.
# custom:
#   code: ERR_SETUP_ENV_INHERITED
deny contains denial if {
	some name in leaked
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is set, so uv would be pointed at another checkout's environment", [name]),
	}
}
