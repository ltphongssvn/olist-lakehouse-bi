package typing

# THE FILE SET IS DECLARED ONCE, in pyproject.toml. mypy checks it only when no
# path is given on the command line, so a path given there silently overrides
# it. The types task and the gate once named different paths, and the task
# reported success over errors the gate refused.

import rego.v1

value_flags := {"--platform", "--config-file", "--python-version", "--cache-dir", "-p", "-m"}

# THE FIRST mypy, so no argv can give this function two answers.
start(argv) := min({index | some index, token in argv; token == "mypy"})

named_paths(argv) := [token |
	some index, token in argv
	index > start(argv)
	not startswith(token, "-")
	not argv[index - 1] in value_flags
]

# METADATA
# title: Type checking must be observed
# description: With no invocation observed, nothing shows the task and the gate agree.
# custom:
#   code: ERR_MYPY_UNOBSERVED
deny contains denial if {
	not input.type_check.invocations[0]
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "no mypy invocation was observed, so agreement cannot be judged",
	}
}

# METADATA
# title: The files mypy checks are declared
# description: Without a declared file set, every caller decides its own.
# custom:
#   code: ERR_MYPY_FILES_UNDECLARED
deny contains denial if {
	input.type_check
	count(input.type_check.files) == 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": "pyproject.toml declares no [tool.mypy] files, so each caller chooses its own",
	}
}

# METADATA
# title: No caller names its own paths
# description: A path on the command line overrides the declared files.
# custom:
#   code: ERR_MYPY_PATHS
deny contains denial if {
	some invocation in input.type_check.invocations
	paths := named_paths(invocation.argv)
	count(paths) > 0
	denial := {
		"code": rego.metadata.rule().custom.code,
		"message": sprintf("%s names %v, overriding the files pyproject.toml declares", [invocation.source, paths]),
	}
}
