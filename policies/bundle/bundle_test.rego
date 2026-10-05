# METADATA
# title: Bundle policy tests
# description: Every rule asserted firing and not firing.
package bundle_test

# BOTH DIRECTIONS, EVERY RULE. A rule with only a passing test is
# indistinguishable from one that cannot fire -- this project shipped exactly
# that: a profile rule using a negative lookahead, which Go's RE2 deliberately
# omits, so it matched NOTHING and looked alive. Only the firing test caught it.
#
# FIRING CASES ASSERT A CODE; NON-FIRING CASES ASSERT A COUNT.
#
# Every firing test used to assert `count(result) == 1`, which coupled it to
# every other rule in the package: a fixture written for one rule that also
# trips a second fails for a reason unrelated to what it tests. That happened in
# policies/tasks and prompted structured denials across the tree.
#
# A code assertion says "this rule fired" and stays true however many others
# also did. A count still belongs on the negative cases, where the claim really
# is "nothing fired at all".

import data.bundle
import rego.v1

# Finds a denial by code, so a test names the rule it is about.
fired(result, code) if {
	some denial in result
	denial.code == code
}

valid_resource := {
	"grants": [{"principal": "example_readers", "privileges": ["SELECT"]}],
	"lifecycle": {"prevent_destroy": true},
}

# --- workspace.host ------------------------------------------------------------

# THE RESOLVED SHAPE, NOT THE YAML SHAPE.
#
# These fixtures previously used {"bundle": {"targets": {...}}} -- the structure
# of databricks.yml as WRITTEN. `bundle validate --output json` collapses
# targets into a flat workspace block, so that path does not exist and the rule
# reading it could never fire. The tests passed anyway, because rule and fixture
# shared the same wrong assumption.
#
# tests/test_policy_fixtures.py asserts these shapes against output captured
# from the real command, so the next divergence fails instead of cancelling out.
pinned_host := {"workspace": {"host": "https://x.example.com"}}

unpinned_host := {"workspace": {"root_path": "/Workspace/Users/someone/.bundle"}}

test_denies_a_bundle_pinning_workspace_host if {
	result := bundle.deny with input as pinned_host
	fired(result, "ERR_BUNDLE_WORKSPACE_HOST")
}

test_allows_a_bundle_without_workspace_host if {
	result := bundle.deny with input as unpinned_host
	count(result) == 0
}

# --- workspace-local groups ----------------------------------------------------

test_denies_a_grant_to_the_users_group if {
	resource := object.union(valid_resource, {"grants": [{"principal": "users"}]})
	result := bundle.deny with input as {"resources": {"schemas": {"s": resource}}}
	fired(result, "ERR_BUNDLE_WORKSPACE_LOCAL_GRANT")
}

test_denies_a_grant_to_the_admins_group if {
	resource := object.union(valid_resource, {"grants": [{"principal": "admins"}]})
	result := bundle.deny with input as {"resources": {"volumes": {"v": resource}}}
	fired(result, "ERR_BUNDLE_WORKSPACE_LOCAL_GRANT")
}

test_allows_a_grant_to_an_account_group if {
	result := bundle.deny with input as {"resources": {"schemas": {"s": valid_resource}}}
	count(result) == 0
}

# --- direct grants to individuals ----------------------------------------------

test_denies_a_direct_grant_to_a_user if {
	# ASSEMBLED, NOT WRITTEN AS A LITERAL. The rule matches on "@" to detect a
	# direct grant to an individual, so the test needs a value containing one --
	# but an email-shaped literal in the tree is a finding for the PII scanner,
	# and suppressing it would make that scanner decoration. Concatenation gives
	# the rule what it needs while leaving no address in the file.
	principal := concat("@", ["someone", "example.invalid"])
	resource := object.union(valid_resource, {"grants": [{"principal": principal}]})
	result := bundle.deny with input as {"resources": {"schemas": {"s": resource}}}
	fired(result, "ERR_BUNDLE_DIRECT_USER_GRANT")
}

# --- prevent_destroy -----------------------------------------------------------

test_denies_a_resource_without_prevent_destroy if {
	resource := object.remove(valid_resource, {"lifecycle"})
	result := bundle.deny with input as {"resources": {"volumes": {"v": resource}}}
	fired(result, "ERR_BUNDLE_NO_PREVENT_DESTROY")
}

test_denies_prevent_destroy_set_to_false if {
	resource := object.union(valid_resource, {"lifecycle": {"prevent_destroy": false}})
	result := bundle.deny with input as {"resources": {"volumes": {"v": resource}}}
	fired(result, "ERR_BUNDLE_NO_PREVENT_DESTROY")
}

# --- catalogs ------------------------------------------------------------------

test_denies_a_declared_catalog if {
	result := bundle.deny with input as {"resources": {"catalogs": {"c": {"name": "x"}}}}
	fired(result, "ERR_BUNDLE_CATALOG_DECLARED")
}

test_allows_a_bundle_with_no_catalogs if {
	result := bundle.deny with input as {"resources": {"schemas": {"s": valid_resource}}}
	count(result) == 0
}

# --- fail closed ---------------------------------------------------------------

test_an_empty_input_denies_nothing_rather_than_erroring if {
	# Vacuous input must not crash evaluation; there is simply nothing to judge.
	result := bundle.deny with input as {}
	count(result) == 0
}

# --- the denial shape ----------------------------------------------------------

# EVERY DENIAL CARRIES BOTH FIELDS. A code with no message is unactionable; a
# message with no code puts callers back to string matching.
test_every_denial_has_a_code_and_a_message if {
	result := bundle.deny with input as pinned_host

	every denial in result {
		is_string(denial.code)
		is_string(denial.message)
	}
}
