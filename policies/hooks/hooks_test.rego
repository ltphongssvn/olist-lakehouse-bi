package hooks_test

import rego.v1

import data.hooks

trailers := {"hook": "commit-msg", "name": "plan steps", "run": "mise run plan:trailers {1}"}

test_both_kept_is_allowed if {
	count(hooks.deny) == 0 with input as {"hooks": {"contract": "hooks/v1", "auto_install": true, "jobs": [trailers]}}
}

test_auto_install_disabled_is_denied if {
	some denial in hooks.deny with input as {"hooks": {"contract": "hooks/v1", "auto_install": false, "jobs": [trailers]}}
	denial.code == "ERR_HOOKS_AUTO_INSTALL_DISABLED"
}

test_trailer_hook_dropped_is_denied if {
	some denial in hooks.deny with input as {"hooks": {"contract": "hooks/v1", "auto_install": true, "jobs": []}}
	denial.code == "ERR_HOOKS_TRAILERS_UNHOOKED"
}
