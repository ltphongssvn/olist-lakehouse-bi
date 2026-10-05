# policies/identity/identity.rego

# METADATA
# title: Project identity policy
# description: Every identity value lives in a declared slot, or under a path exempt for a reason.
# entrypoint: true
package identity

# contracts/project-identity.toml is the one place identity is written. Any other copy
# drifts the moment the project is renamed or generated anew (D.52).

import rego.v1

_exempt(path) if {
	some prefix in input.identity_inventory.exempt
	startswith(path, prefix)
}

# METADATA
# title: Identity lives only in declared slots
# description: A value outside a slot and outside an exempt path is a copy that will drift.
# custom:
#   code: ERR_IDENTITY_LITERAL
deny contains denial if {
	some occurrence in input.identity_inventory.occurrences
	not occurrence.slot
	not _exempt(occurrence.path)
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s:%d holds %s outside a declared slot", [occurrence.path, occurrence.number, occurrence.value]),
	}
}

# METADATA
# title: The identity inventory is present
# description: Without it the rule above judges nothing, and an empty judgement reads as a pass.
# custom:
#   code: ERR_IDENTITY_INPUT_MISSING
deny contains denial if {
	not input.identity_inventory
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no identity_inventory was supplied, so no identity literal was judged",
	}
}
