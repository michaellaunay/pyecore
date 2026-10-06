"""Regression contracts for restricted dynamic operation compilation."""
import inspect

import pytest
from RestrictedPython import safe_builtins

from pyecore.ecore import EClass, EDataType, EInt, EOperation, EParameter


def test_operation_environments_are_private():
    before = dict(safe_builtins)
    a, b = EClass('A'), EClass('B')
    a.eOperations.append(EOperation('first'))
    a.eOperations.append(EOperation('second'))
    b.eOperations.append(EOperation('first'))
    functions = [a.python_class.first, a.python_class.second,
                 b.python_class.first]
    assert safe_builtins == before
    for f in functions:
        assert f.__globals__ is not safe_builtins
        assert f.__globals__['__builtins__'] is not safe_builtins
        assert 'open' not in f.__globals__['__builtins__']
    for f, g in zip(functions, functions[1:]):
        assert f.__globals__ is not g.__globals__
        assert f.__globals__['__builtins__'] is not g.__globals__['__builtins__']
    functions[0].__globals__['__builtins__']['NotImplementedError'] = ValueError
    with pytest.raises(ValueError):
        a().first()
    with pytest.raises(NotImplementedError):
        a().second()
    with pytest.raises(NotImplementedError):
        b().first()


@pytest.mark.parametrize('name', ['class', 'return', 'async', 'match', 'café'])
def test_operation_names_and_exception(name):
    cls = EClass('A')
    op = EOperation(name)
    cls.eOperations.append(op)
    method = getattr(cls(), op.normalized_name())
    assert str(inspect.signature(method)) == '()'
    with pytest.raises(NotImplementedError, match='is not yet implemented'):
        method()
    with pytest.raises(TypeError):
        method(1)


@pytest.mark.parametrize('name', [None, '', 'a-b', '1name', 'x():\n pass\ndef other', '_private'])
def test_invalid_operation_name(name):
    cls = EClass('A')
    with pytest.raises(SyntaxError):
        cls.eOperations.append(EOperation(name))
    assert name not in cls.python_class.__dict__
    assert 'other' not in cls.python_class.__dict__
    # Notification happens after insertion: the existing model contract keeps
    # the rejected operation in containment. No generated method is installed.
    assert cls.eOperations[0].eContainingClass is cls


@pytest.mark.parametrize('name', [None, 'class', '', 'a-b', 'x=1', '*args', '_private'])
def test_invalid_parameter_name(name):
    cls = EClass('A')
    with pytest.raises(SyntaxError):
        cls.eOperations.append(EOperation('op', params=[EParameter(name, required=True)]))
    assert 'op' not in cls.python_class.__dict__


@pytest.mark.parametrize('default', [None, 0, False, '', 'hello', "quote'\nline", "'); raise ValueError('injected"])
def test_defaults_are_values(default):
    dtype = EDataType('DefaultType', eType=object, default_value=default)
    cls = EClass('A')
    cls.eOperations.append(EOperation('op', params=[EParameter('value', dtype)]))
    method = cls().op
    assert inspect.signature(method).parameters['value'].default == default
    with pytest.raises(NotImplementedError):
        method()
    with pytest.raises(NotImplementedError):
        method(value=default)


def test_required_parameters_and_explicit_self():
    cls = EClass('A')
    cls.eOperations.append(EOperation('op', params=[EParameter('self', required=True),
                                                  EParameter('value', EInt, required=True)]))
    assert str(inspect.signature(cls().op)) == '(value)'
    with pytest.raises(TypeError):
        cls().op()
    with pytest.raises(NotImplementedError, match=r'Method op\(self, value\)'):
        cls().op(42)


@pytest.mark.parametrize('params', [
    [EParameter('x', EInt), EParameter('y', required=True)],
    [EParameter('x', required=True), EParameter('x', required=True)],
])
def test_invalid_signature(params):
    cls = EClass('A')
    with pytest.raises(SyntaxError):
        cls.eOperations.append(EOperation('op', params=params))
    assert 'op' not in cls.python_class.__dict__


def test_restricted_compiler_and_builtins_remain_active(monkeypatch):
    cls = EClass('A')
    monkeypatch.setattr(EOperation, 'to_code', lambda self: 'def op(self):\n    return self.__class__')
    with pytest.raises(SyntaxError):
        cls.eOperations.append(EOperation('op'))
    assert 'op' not in cls.python_class.__dict__
    monkeypatch.setattr(EOperation, 'to_code', lambda self: 'import os\ndef op(self):\n    pass')
    with pytest.raises(ImportError, match='__import__'):
        cls.eOperations.append(EOperation('op'))
    assert 'op' not in cls.python_class.__dict__


def test_default_collections_are_distinct_between_classes():
    dtype = EDataType('DefaultList', eType=list, default_value=[])
    a, b = EClass('A'), EClass('B')
    for cls in (a, b):
        cls.eOperations.append(EOperation('op', params=[EParameter('value', dtype)]))
    first = inspect.signature(a().op).parameters['value'].default
    second = inspect.signature(b().op).parameters['value'].default
    first.append(42)
    assert second == []
    assert dtype.default_value == []
