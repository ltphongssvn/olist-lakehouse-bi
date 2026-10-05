package parsing_test

import rego.v1

import data.parsing

test_a_raw_parse_is_denied if {
	some denial in parsing.deny with input as {"raw_parses": {
		"files_scanned": 1, "uses": [{"path": "x.py", "line": 2, "call": "json.loads"}],
	}}
	denial.code == "ERR_PARSE_RAW"
}

test_none_is_allowed if {
	count(parsing.deny) == 0 with input as {"raw_parses": {"files_scanned": 1, "uses": []}}
}

test_an_absent_inventory_is_denied if {
	some denial in parsing.deny with input as {}
	denial.code == "ERR_PARSE_UNOBSERVED"
}
