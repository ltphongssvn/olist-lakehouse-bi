# policies/deps/add/add.rego

# METADATA
# title: Dependency addition policy
# description: Adding a package keeps the lock current and changes nothing already locked.
# entrypoint: true
package deps.add

# uv never treats a lock as outdated because new versions were released, so an
# upgrade is a separate, explicit act. An addition that changes or removes an
# already-locked package is refused, and the task restores both files.

import rego.v1

# METADATA
# title: The lock matches pyproject.toml
# description: uv lock --check failed after the addition.
# custom:
#   code: ERR_DEPS_LOCK_STALE
deny contains denial if {
	input.deps_change
	not input.deps_change.lock_current
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "uv.lock does not match pyproject.toml after the addition",
	}
}

# METADATA
# title: The package landed
# description: The requested package must appear in pyproject.toml or a dependency group.
# custom:
#   code: ERR_DEPS_NOT_ADDED
deny contains denial if {
	input.deps_change
	not input.deps_change.landed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is not declared after uv add", [input.deps_change.package]),
	}
}

# METADATA
# title: No locked package changes version
# description: Upgrading is a separate, explicit act, never a side effect of adding.
# custom:
#   code: ERR_DEPS_EXISTING_CHANGED
deny contains denial if {
	some name in input.deps_change.changed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s changed version while adding %s", [name, input.deps_change.package]),
	}
}

# METADATA
# title: No locked package is removed
# description: An addition must not drop anything already locked.
# custom:
#   code: ERR_DEPS_REMOVED
deny contains denial if {
	some name in input.deps_change.removed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s was removed from the lock while adding %s", [name, input.deps_change.package]),
	}
}
