# METADATA
# title: Bundle policy
# description: Rules the Declarative Automation Bundle must satisfy.
# entrypoint: true
package bundle

# EVERY RULE HERE COST SOMETHING TO LEARN.
#
# A comment explaining a past failure prevents nothing -- the next person adds
# the field back, the build goes green, and the failure returns weeks later
# wearing a different error message. These are the same lessons, enforced.
#
# FAIL CLOSED. Rules are written so a MISSING field denies rather than leaving
# the decision undefined. Absence must not mean permission.
#
# DENIALS ARE OBJECTS WITH CODES, AND THE CODE COMES FROM THE ANNOTATION.
#
# A string denial can only be tested by counting results or matching prose, and
# a count couples every test to every other rule in the package. Writing the
# code in both the annotation and the body would be two copies of one fact;
# rego.metadata.rule() reads the rule's own annotation at evaluation time, so
# the metadata is the single source and `opa inspect -a` can enumerate it.
#
# NOTHING BUT YAML GOES INSIDE A # METADATA BLOCK. It is parsed as YAML and
# consumes every following comment line until a non-comment line ends it, so
# prose fails the moment it contains a colon. Explanation belongs BELOW the rule
# head, where the annotation has already closed.

import rego.v1

# METADATA
# title: workspace.host must not be pinned
# description: It forces host-based profile resolution, which CI cannot satisfy.
# custom:
#   code: ERR_BUNDLE_WORKSPACE_HOST
deny contains denial if {
	# workspace.host sends bundle commands down a DIFFERENT auth path than every
	# other command: it forces host-based profile resolution, which requires a
	# .databrickscfg that does not exist on a CI runner. `databricks auth
	# describe` and `databricks bundle validate` ran in the same CI step with
	# the same OAuth M2M credentials and only the second failed. Cost: four CI
	# runs.
	#
	# READS THE RESOLVED SHAPE, NOT THE YAML SHAPE. An earlier version iterated
	# input.bundle.targets -- the structure of databricks.yml as WRITTEN.
	# `bundle validate --output json` collapses targets into a flat workspace
	# block, so that path does not exist and the rule could never fire. It
	# passed 21 tests, because the fixtures were invented from the same wrong
	# assumption. Two errors in the same direction cancel out and look like
	# correctness.
	input.workspace.host
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"workspace.host is set. That forces host-based profile resolution, %s",
			["which needs a .databrickscfg that CI does not have."],
		),
	}
}

# METADATA
# title: Workspace-local groups cannot hold UC privileges
# description: The API reports PRINCIPAL_DOES_NOT_EXIST, which reads like a missing group.
# custom:
#   code: ERR_BUNDLE_WORKSPACE_LOCAL_GRANT
deny contains denial if {
	# It is a category error, not a missing group. Cost: one failed deploy.
	some kind in {"schemas", "volumes"}
	some name, resource in input.resources[kind]
	some grant in resource.grants
	grant.principal in {"users", "admins"}
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"%s %q grants to %q, a WORKSPACE-LOCAL group. Those cannot %s",
			[kind, name, grant.principal, "hold Unity Catalog privileges."],
		),
	}
}

# METADATA
# title: Grants go to groups, not individuals
# description: An email address in a principal field is a direct grant.
# custom:
#   code: ERR_BUNDLE_DIRECT_USER_GRANT
deny contains denial if {
	# UC guidance is to use groups and avoid direct grants to individual
	# principals, so a second identity joins a group rather than accumulating
	# its own privileges.
	some kind in {"schemas", "volumes"}
	some name, resource in input.resources[kind]
	some grant in resource.grants
	contains(grant.principal, "@")
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"%s %q grants directly to the user %q. Grant to a group %s",
			[kind, name, grant.principal, "instead; individuals join the group."],
		),
	}
}

# METADATA
# title: Managed objects declare prevent_destroy
# description: bundle destroy force-deletes managed schemas and takes their data.
# custom:
#   code: ERR_BUNDLE_NO_PREVENT_DESTROY
deny contains denial if {
	# The guard is best-effort -- databricks/cli#4872 reports it being ignored
	# -- but declaring it costs nothing and omitting it removes even the intent.
	some kind in {"schemas", "volumes"}
	some name, resource in input.resources[kind]
	not resource.lifecycle.prevent_destroy
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"%s %q does not declare lifecycle.prevent_destroy. %s",
			[kind, name, "bundle destroy force-deletes managed objects and their data."],
		),
	}
}

# METADATA
# title: Catalogs are a prerequisite, not a bundle resource
# description: They are always created and cannot be bound to an existing one.
# custom:
#   code: ERR_BUNDLE_CATALOG_DECLARED
deny contains denial if {
	# The catalog already exists and cannot be adopted by a bundle
	# (databricks/cli#4842), so declaring it guarantees a create-conflict with
	# no way out. It is a checked prerequisite instead.
	input.resources.catalogs
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"resources.catalogs is declared. Catalogs are always CREATED %s",
			["and cannot be bound (databricks/cli#4842); use check:prereqs."],
		),
	}
}
