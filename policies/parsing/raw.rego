# METADATA
# title: Parsing policy
# description: Every external read is validated where it enters.
# entrypoint: true
package parsing

# A PARSE STRAIGHT INTO A MODEL IS SANCTIONED; any other lets untyped data into
# the code, where nothing checks its shape until something breaks on it. The
# observer reads the syntax tree; this decides.
#
# ABSENCE THROUGH A HELPER RULE, as the typing policy proves it. The inline form
# negating a comparison on a missing input did not fire.

import rego.v1

observed if input.raw_parses.files_scanned >= 1

# METADATA
# title: The parses must be observed
# description: An inventory nobody produced cannot show the code parses nothing raw.
# custom:
#   code: ERR_PARSE_UNOBSERVED
deny contains denial if {
	not observed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no parse inventory was observed, so nothing can be judged clean",
	}
}

# METADATA
# title: No raw parse
# description: A parse that does not go straight into a model enters unvalidated.
# custom:
#   code: ERR_PARSE_RAW
deny contains denial if {
	some use in input.raw_parses.uses
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s:%d parses with %s outside a model", [use.path, use.line, use.call]),
	}
}
