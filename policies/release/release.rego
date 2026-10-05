# policies/release/release.rego

# METADATA
# title: Release policy
# description: A release tag names the assignment whose run it exports.
# entrypoint: true
package release

# EVALUATED BY release ITSELF, before anything merges. The gate's payload holds
# no release, so no rule here fires there.

import rego.v1

# METADATA
# title: A tag names its assignment and a version
# description: assignment-02-v1 on Assignment 1's run would point a regrade at the wrong work.
# custom:
#   code: ERR_RELEASE_TAG_MISMATCH
deny contains denial if {
	release := input.release
	not regex.match(sprintf("^%s-v[0-9]+$", [release.target.assignment]), release.tag)
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf(
			"tag %s does not name %s with a version, e.g. %s-v1",
			[release.tag, release.target.assignment, release.target.assignment],
		),
	}
}
