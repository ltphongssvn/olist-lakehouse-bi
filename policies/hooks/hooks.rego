# METADATA
# title: Hooks policy
# description: Configured hooks keep reaching every checkout, and the trailer hook stays.
# entrypoint: true
package hooks

# LEFTHOOK RE-SYNCS HOOKS ITSELF while auto-install is on: adding commit-msg to
# lefthook.yml reached every checkout the next time any hook ran. That holds only
# while auto-install stays enabled, and G.4's zero-latency refusal holds only
# while the commit-msg job running plan:trailers stays configured.

import rego.v1

# METADATA
# title: The hooks configuration must be observed
# description: A configuration nobody read cannot show its hooks still arrive.
# custom:
#   code: ERR_HOOKS_UNOBSERVED
deny contains denial if {
	not input.hooks.contract
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the hooks configuration was not observed, so nothing shows its hooks arrive",
	}
}

# METADATA
# title: Hooks install themselves
# description: Without auto-install, a new hook reaches no checkout until someone remembers.
# custom:
#   code: ERR_HOOKS_AUTO_INSTALL_DISABLED
deny contains denial if {
	input.hooks.auto_install == false
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no_auto_install is set, so a hook added to lefthook.yml reaches no checkout by itself",
	}
}

# METADATA
# title: The trailer hook stays configured
# description: Without it, a commit naming no plan step is refused only in CI.
# custom:
#   code: ERR_HOOKS_TRAILERS_UNHOOKED
deny contains denial if {
	input.hooks.contract
	count([job |
		some job in input.hooks.jobs
		job.hook == "commit-msg"
		contains(job.run, "plan:trailers")
	]) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no commit-msg hook runs plan:trailers, so a commit naming no step is caught only in CI",
	}
}
