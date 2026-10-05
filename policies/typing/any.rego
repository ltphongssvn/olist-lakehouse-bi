# METADATA
# title: Typing policy
# description: No Any is written or implied in this repository's code.
# entrypoint: true
package typing

# WHY THIS IS A POLICY. mypy's strict mode does not include disallow_any_explicit,
# so an explicit Any was never checked here. The observer records every Any --
# written, or implied by a missing annotation -- and this decides over that
# record, beside every other rule this repository judges its own code by.
#
# FAIL CLOSED. An absent or empty inventory is unobserved, never clean.

import rego.v1

observed if input.any_inventory.files_scanned >= 1

# METADATA
# title: The inventory must exist
# description: An inventory nobody produced cannot show the code is clean.
# custom:
#   code: ERR_ANY_UNOBSERVED
deny contains denial if {
	not observed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no Any inventory was observed, so nothing can be judged clean",
	}
}

# METADATA
# title: No explicit Any
# description: Any written in source switches checking off where it stands.
# custom:
#   code: ERR_ANY_EXPLICIT
deny contains denial if {
	some use in input.any_inventory.uses
	use.form == "explicit"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s:%d names Any explicitly", [use.path, use.line]),
	}
}

# METADATA
# title: No implicit Any
# description: A parameter or return left unannotated is Any without the word.
# custom:
#   code: ERR_ANY_IMPLICIT
deny contains denial if {
	some use in input.any_inventory.uses
	use.form == "implicit"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s:%d leaves %s unannotated, which reads as Any", [use.path, use.line, use.name]),
	}
}
