# policies/template/publish/publish.rego

# METADATA
# title: Template publishing policy
# description: Only a clean generated project with no remote is published.
# entrypoint: true
package template.publish

# An ACTION policy (D.60): template:publish builds the request and asks in the same call,
# so every rule first requires it, and the repository gate, which supplies none, is silent.

import rego.v1

# METADATA
# title: The destination was generated
# description: Without .copier-answers.yml it is not a generated project.
# custom:
#   code: ERR_PUBLISH_NOT_GENERATED
deny contains denial if {
	input.template_publish
	not input.template_publish.answers_present
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s holds no .copier-answers.yml", [input.template_publish.destination]),
	}
}

# METADATA
# title: The destination is clean
# description: Publishing pushes commits; uncommitted work would be left behind unseen.
# custom:
#   code: ERR_PUBLISH_DIRTY
deny contains denial if {
	input.template_publish
	not input.template_publish.clean
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s has uncommitted changes", [input.template_publish.destination]),
	}
}

# METADATA
# title: The destination is not yet published
# description: A project is published once; a second remote would split its history.
# custom:
#   code: ERR_PUBLISH_HAS_REMOTE
deny contains denial if {
	input.template_publish.has_remote
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s already has a remote", [input.template_publish.destination]),
	}
}

# METADATA
# title: The destination's hooks are not yet installed
# description: Its own pre-push gate needs origin/develop, which only this push creates (D.62).
# custom:
#   code: ERR_PUBLISH_HOOKS_INSTALLED
deny contains denial if {
	input.template_publish.hooks_installed
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s has hooks installed: publish before setup", [input.template_publish.destination]),
	}
}

# METADATA
# title: The GitHub repository holds nothing yet
# description: Pushing onto existing history would mix two projects (D.62).
# custom:
#   code: ERR_PUBLISH_REMOTE_POPULATED
deny contains denial if {
	input.template_publish.remote == "populated"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s already exists on GitHub with commits", [input.template_publish.repository]),
	}
}

# METADATA
# title: The GitHub repository's state was observed
# description: A remote nobody could see is not assumed safe to push to (D.62).
# custom:
#   code: ERR_PUBLISH_REMOTE_UNKNOWN
deny contains denial if {
	input.template_publish.remote == "unknown"
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s could not be observed on GitHub", [input.template_publish.repository]),
	}
}
