package typing_test

import rego.v1

import data.typing

test_a_missing_inventory_is_denied if {
	some denial in typing.deny with input as {}
	denial.code == "ERR_ANY_UNOBSERVED"
}

test_a_clean_inventory_is_allowed if {
	codes := {d.code | some d in typing.deny} with input as {"any_inventory": {"files_scanned": 3, "uses": []}}
	count({code | some code in codes; startswith(code, "ERR_ANY_")}) == 0
}

test_an_explicit_any_is_denied if {
	some denial in typing.deny with input as {"any_inventory": {
		"files_scanned": 1,
		"uses": [{"path": "x.py", "line": 2, "form": "explicit", "name": "Any"}],
	}}
	denial.code == "ERR_ANY_EXPLICIT"
}

test_an_implicit_any_is_denied if {
	some denial in typing.deny with input as {"any_inventory": {
		"files_scanned": 1,
		"uses": [{"path": "x.py", "line": 1, "form": "implicit", "name": "x"}],
	}}
	denial.code == "ERR_ANY_IMPLICIT"
}
