# policies/template/init/init.rego

# METADATA
# title: Template initialisation policy
# description: Only a generated project, not yet a repository and outside this one, is made one.
# entrypoint: true
package template.init

# An ACTION policy (D.58): template:init builds the request and asks in the same call, so
# every rule first requires it, and the repository gate, which supplies none, judges nothing.

import rego.v1

# METADATA
# title: The destination was generated
# description: Without .copier-answers.yml it is not a generated project, and copier update has no base.
# custom:
#   code: ERR_INIT_NOT_GENERATED
deny contains denial if {
	input.template_init
	not input.template_init.answers_present
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s holds no .copier-answers.yml, so it was not generated", [input.template_init.destination]),
	}
}

# METADATA
# title: The destination is not yet a repository
# description: Initialising over an existing repository would rewrite history someone already has.
# custom:
#   code: ERR_INIT_ALREADY_REPOSITORY
deny contains denial if {
	input.template_init.already_repository
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is already a git repository", [input.template_init.destination]),
	}
}

# METADATA
# title: The destination is outside the source
# description: A repository nested inside the template would be committed into it.
# custom:
#   code: ERR_INIT_INSIDE_SOURCE
deny contains denial if {
	input.template_init.inside_source
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is inside the template repository", [input.template_init.destination]),
	}
}
