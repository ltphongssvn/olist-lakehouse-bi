# policies/machine/environment/environment.rego

# METADATA
# title: Environment policy
# description: After sync, the environment matches a lock that changed.
# entrypoint: true
package machine.environment

# A pull that changed uv.lock leaves .venv behind its own lock unless something
# installs it. NAMESPACED under machine. because it judges a process's environment.

import rego.v1

# METADATA
# title: The environment was observed
# description: An environment nobody looked at cannot show it follows the lock.
# custom:
#   code: ERR_ENV_UNOBSERVED
deny contains denial if {
	not input.environment_sync
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the environment was not observed after sync",
	}
}

# METADATA
# title: A changed lock was installed
# description: uv.lock changed in the pull, and uv sync --locked did not succeed.
# custom:
#   code: ERR_ENV_STALE
deny contains denial if {
	input.environment_sync.lock_changed
	not input.environment_sync.installed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"uv.lock changed but the environment was not brought to it (uv sync exited %v)",
			[input.environment_sync.install_exit_code],
		),
	}
}
