Dynamic operation compilation
=============================

Dynamic EOperations generate placeholders with their declared parameter names
and defaults. Calling a placeholder raises NotImplementedError; Python's usual
signature checks still raise TypeError for missing or extra arguments. Python
keywords used as operation names gain a trailing underscore. Parameter keywords
and non-identifiers are rejected with SyntaxError, as are signatures rejected by
RestrictedPython (including restricted names beginning with an underscore).

Each operation is compiled with RestrictedPython.compile_restricted and executed
with a fresh globals dictionary containing a separate copy of safe_builtins under
``__builtins__``. Neither the library's shared builtins dictionary nor another
operation's environment is modified. RestrictedPython restricts a language subset;
it is not a security sandbox for untrusted models or resources.

Compilation is triggered by a notification after an operation has been inserted
into its containing class. A compilation exception propagates and no method is
installed, but the operation remains in the model. This existing notification and
containment behavior is preserved; callers must handle that partial model state.

Dependency policy for the CPython 3.12/3.13/3.14 migration: RestrictedPython
>=8.5,<8.6. Version 8.5 is the available release qualified on all three interpreters
in source and wheel installations. The narrow range avoids claiming qualification
of untested minor releases; widen it after running this matrix again. Version 8.1
introduced Python 3.14 support, but is not locally qualified by this migration.

References:

* https://pypi.org/project/RestrictedPython/8.5/
* https://restrictedpython.readthedocs.io/en/stable/usage/basic_usage.html
* https://restrictedpython.readthedocs.io/en/latest/usage/security_considerations.html
