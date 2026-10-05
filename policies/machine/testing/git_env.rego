# policies/machine/testing/git_env.rego

# METADATA
# title: Test isolation policy
# description: A test session holds none of git's repository-local variables.
# entrypoint: true
package machine.testing

# git exports GIT_DIR and its siblings to hooks, and they override any cwd or -C,
# so a test's throwaway git commands acted on the real repository. NAMESPACED
# under machine. because it judges a process's environment, not the repository:
# the pre-push gate itself legitimately runs with GIT_DIR set.

import rego.v1

leaked contains name if {
	some name in input.git_isolation.present
	name in input.git_isolation.local_variables
}

# METADATA
# title: The session's git environment must be observed
# description: An environment nobody looked at cannot show it is isolated.
# custom:
#   code: ERR_TEST_GIT_ENV_UNOBSERVED
deny contains denial if {
	not input.git_isolation.local_variables[0]
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "the test session's git environment was not observed",
	}
}

# METADATA
# title: No repository-local git variable reaches a test
# description: Any one of them redirects a test's git commands to another repository.
# custom:
#   code: ERR_TEST_GIT_ENV_LEAKED
deny contains denial if {
	some name in leaked
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s is set, so a test's git commands would act on the repository it names", [name]),
	}
}
