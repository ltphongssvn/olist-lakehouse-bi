package typing_test

import rego.v1

import data.typing

bare := ["uv", "run", "mypy", "--platform", "darwin"]

test_a_bare_invocation_is_allowed if {
	denials := {d.code | some d in typing.deny} with input as {"type_check": {
		"files": ["scripts"], "invocations": [{"source": "task:types", "argv": bare}],
	}}
	not "ERR_MYPY_PATHS" in denials
}

test_a_named_path_is_denied if {
	some denial in typing.deny with input as {"type_check": {
		"files": ["scripts"], "invocations": [{"source": "task:types", "argv": array.concat(bare, ["scripts"])}],
	}}
	denial.code == "ERR_MYPY_PATHS"
}
