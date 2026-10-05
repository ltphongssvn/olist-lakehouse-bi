# policies/template/identity/identity.rego

# METADATA
# title: Template identity policy
# description: Only a fresh generated project -- one commit, no remote -- takes its identity.
# entrypoint: true
package template.identity

# An ACTION policy (D.59): template:identity builds the request and asks in the same call,
# so every rule first requires it, and the repository gate, which supplies none, is silent.

import rego.v1

# METADATA
# title: The destination was generated
# description: Without .copier-answers.yml it is not a generated project.
# custom:
#   code: ERR_IDENTITY_NOT_GENERATED
deny contains denial if {
	input.template_identity
	not input.template_identity.answers_present
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s holds no .copier-answers.yml", [input.template_identity.destination]),
	}
}

# METADATA
# title: The project is fresh
# description: Identity is taken once, as the second commit; later history is the project its own.
# custom:
#   code: ERR_IDENTITY_NOT_FRESH
deny contains denial if {
	request := input.template_identity
	request.commits != 1
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s holds %d commits, not one", [request.destination, request.commits]),
	}
}

# METADATA
# title: The project is not yet published
# description: Once a remote exists, identity changes go through a pull request.
# custom:
#   code: ERR_IDENTITY_HAS_REMOTE
deny contains denial if {
	input.template_identity.has_remote
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s already has a remote", [input.template_identity.destination]),
	}
}
