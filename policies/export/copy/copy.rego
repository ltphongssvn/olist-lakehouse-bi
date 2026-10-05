# policies/export/copy/copy.rego

# METADATA
# title: Export copy policy
# description: Only a released export is copied out, never over an existing file, and verified.
# entrypoint: true
package export.copy

# Every rule needs an export_copy input, so the gate's own payload leaves this quiet.

import rego.v1

# METADATA
# title: Only a released assignment is copied out
# description: The copy is named for its release tag; with no tag there is no release.
# custom:
#   code: ERR_EXPORT_UNRELEASED
deny contains denial if {
	input.export_copy.tag == null
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s has no release tag; release it first", [input.export_copy.assignment]),
	}
}

# METADATA
# title: The assignment has exactly one export
# description: None, or more than one, leaves nothing unambiguous to copy.
# custom:
#   code: ERR_EXPORT_SOURCE_MISSING
deny contains denial if {
	input.export_copy
	not input.export_copy.source_exists
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("no single HTML export in %s", [input.export_copy.source]),
	}
}

# METADATA
# title: An existing file is never overwritten
# description: The destination already exists; remove or rename it deliberately.
# custom:
#   code: ERR_EXPORT_DESTINATION_EXISTS
deny contains denial if {
	input.export_copy.destination_existed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s already exists", [input.export_copy.destination]),
	}
}

# METADATA
# title: The copy matches its source exactly
# description: A copy whose SHA-256 differs from the source is not the released file.
# custom:
#   code: ERR_EXPORT_COPY_MISMATCH
deny contains denial if {
	input.export_copy.copy_sha256 != null
	input.export_copy.copy_sha256 != input.export_copy.source_sha256
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the copy's SHA-256 differs from the released export's",
	}
}
