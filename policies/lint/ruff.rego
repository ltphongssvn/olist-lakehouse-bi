# METADATA
# title: Lint policy
# description: The local gate lints as CI does, with no cache to go stale.
# entrypoint: true
package lint

# RUFF'S CACHE DOES NOT KEY ON WHICH MODULES EXIST. It decides whether an import
# is first-party by whether the module is on disk, so a module created after the
# file importing it was linted left a stale classification the laptop kept
# passing -- while CI, which has no cache, refused the same file with I001.
#
# ruff format IS EXEMPT: formatting does not depend on which modules exist.

import rego.v1

ruff_checks contains invocation if {
	some invocation in input.invocations.invocations
	some index, token in invocation.argv
	token == "ruff"
	invocation.argv[index + 1] == "check"
}

# METADATA
# title: Linting must be observed
# description: A gate that stopped running ruff check must not read as clean.
# custom:
#   code: ERR_RUFF_UNOBSERVED
deny contains denial if {
	count(ruff_checks) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no ruff check was observed in any task or gate, so nothing is linted",
	}
}

# METADATA
# title: Every ruff check runs cache-free
# description: A cached check can pass a tree CI refuses.
# custom:
#   code: ERR_RUFF_CACHED
deny contains denial if {
	some invocation in ruff_checks
	not "--no-cache" in invocation.argv
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s runs ruff check with a cache CI does not have", [invocation.source]),
	}
}
