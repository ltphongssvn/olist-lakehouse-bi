# policies/source/restore/restore.rego

# METADATA
# title: Source restore policy
# description: Only tracked paths are restored to HEAD, and only when some are named.
# entrypoint: true
package source.restore

# git restore --source=HEAD on a path HEAD has never seen drops the file, so such a
# path is refused rather than silently deleted.

import rego.v1

# METADATA
# title: At least one path is named
# description: A restore that names nothing has nothing to act on.
# custom:
#   code: ERR_RESTORE_NO_PATHS
deny contains denial if {
	input.restore_plan.paths == []
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "name at least one path to restore",
	}
}

# METADATA
# title: Only paths HEAD knows are restored
# description: Restoring a path HEAD has never seen would drop the file.
# custom:
#   code: ERR_RESTORE_UNTRACKED
deny contains denial if {
	some state in input.restore_plan.paths
	not state.in_head
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is not in HEAD; restoring it would delete it", [state.path]),
	}
}
