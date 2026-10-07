"""Contracts for inheritance isolation and annotation-independent reflection."""
import inspect
import sys
from typing import ForwardRef

import pytest
from pyecore.ecore import EClass, EObject, EMetaclass, MetaEClass, Metasubinstance


@pytest.fixture(autouse=True)
def restore_legacy_mro():
    # Keep the pre-fix red suite independent; production must never mutate this.
    original = Metasubinstance.mro
    yield
    Metasubinstance.mro = original


def graph():
    root = EClass('Root')
    left = EClass('Left', superclass=root)
    right = EClass('Right', superclass=root)
    return root, left, right


def test_dynamic_diamond_resolution_and_mutation():
    root, left, right = graph()
    left.python_class.choose = lambda self: 'left'
    right.python_class.choose = lambda self: 'right'
    leaf = EClass('Leaf', superclass=(left, right))
    assert leaf().choose() == 'left'
    assert leaf.python_class.__mro__[:4] == tuple(x.python_class for x in (leaf, left, right, root))
    leaf.eSuperTypes.clear()
    leaf.eSuperTypes.extend((right, left))
    assert leaf().choose() == 'right'
    assert root.python_class in leaf.python_class.__mro__


@pytest.mark.parametrize('mutation', [False, True])
def test_non_c3_fallback_is_local(mutation):
    original = Metasubinstance.mro
    root, left, right = graph()
    xy = EClass('XY', superclass=(left, right))
    yx = EClass('YX', superclass=(right, left))
    if mutation:
        conflict = EClass('Conflict', superclass=xy)
        conflict.eSuperTypes.append(yx)
    else:
        conflict = EClass('Conflict', superclass=(xy, yx))
    assert isinstance(conflict(), xy.python_class)
    assert isinstance(conflict(), yx.python_class)
    assert len(conflict.python_class.__mro__) == len(set(conflict.python_class.__mro__))
    assert Metasubinstance.mro is original
    fresh = EClass('Fresh', superclass=(left, right))
    assert fresh.python_class.__mro__[:4] == tuple(x.python_class for x in (fresh, left, right, root))
    # Static inconsistent C3 must still fail after the local dynamic fallback.
    with pytest.raises(TypeError):
        MetaEClass('Invalid', (xy.python_class, yx.python_class), {'__module__': __name__})


def test_failed_cycle_does_not_change_global_or_python_bases():
    cls = EClass('Cycle')
    original = Metasubinstance.mro
    bases, mro = cls.python_class.__bases__, cls.python_class.__mro__
    with pytest.raises(RecursionError):
        cls.eSuperTypes.append(cls)
    assert Metasubinstance.mro is original
    assert cls.python_class.__bases__ == bases
    assert cls.python_class.__mro__ == mro
    # Notifications happen after insertion: retain and expose this prior contract.
    assert cls in cls.eSuperTypes
    cls.eSuperTypes.remove(cls)
    assert EClass('AfterFailure').python_class.__bases__ == (EObject,)


def test_static_diamond_operations_and_fullargspec():
    class Root(EObject, metaclass=MetaEClass):
        def choose(self, value: int = 3, *, flag=True) -> int:
            return value
    class Left(Root):
        def choose(self, value=4):
            return value + 1
    class Right(Root):
        pass
    class Leaf(Left, Right):
        pass
    assert Leaf.__mro__[:4] == (Leaf, Left, Right, Root)
    assert Leaf().choose() == 5
    spec = inspect.getfullargspec(Root.choose)
    assert spec.args == ['self', 'value'] and spec.defaults == (3,)
    assert spec.kwonlyargs == ['flag']
    op = Root.eClass.eOperations[0]
    assert [p.name for p in op.eParameters] == ['self', 'value']
    assert [p.required for p in op.eParameters] == [True, False]


@pytest.mark.parametrize('style', ['future', 'forwardref', 'deferred'])
def test_annotation_reflection_does_not_resolve_missing_names(style):
    namespace = {'ForwardRef': ForwardRef}
    prefix = 'from __future__ import annotations\n' if style == 'future' else ''
    annotation = "ForwardRef('Missing')" if style == 'forwardref' else 'Missing'
    if style == 'deferred' and sys.version_info < (3, 14):
        # Earlier Python needs a literal forward reference, not native deferral.
        annotation = "'Missing'"
    exec(compile(prefix + f'def operation(self, value: {annotation} = 7) -> {annotation}:\n    return value\n', '<annotations>', 'exec', dont_inherit=True), namespace)
    function = namespace['operation']
    cls = MetaEClass('Annotated', (EObject,), {'__module__': __name__, 'operation': function})
    op = cls.eClass.eOperations[0]
    assert [p.name for p in op.eParameters] == ['self', 'value']
    assert [p.required for p in op.eParameters] == [True, False]
    assert cls().operation() == 7
    if style == 'forwardref':
        assert isinstance(inspect.getfullargspec(function).annotations['value'], ForwardRef)
    if style == 'deferred' and sys.version_info >= (3, 14):
        import annotationlib
        assert isinstance(annotationlib.get_annotations(function, format=annotationlib.Format.FORWARDREF)['value'], annotationlib.ForwardRef)
        with pytest.raises((NameError, TypeError)):
            inspect.getfullargspec(function)


def test_decorated_static_and_dynamic_bases():
    @EMetaclass
    class Decorated:
        def operation(self, value=2):
            return value
    dynamic = EClass('Dynamic', superclass=Decorated.eClass)
    assert dynamic().operation() == 2
    class Static(dynamic, metaclass=MetaEClass):
        pass
    assert Static().operation() == 2
    assert issubclass(Static, Decorated)
    assert Static.eClass.eSuperTypes[0] is dynamic.python_class.eClass


def test_fallback_order_and_recovery():
    root, left, right = graph()
    xy = EClass('XY', superclass=(left, right))
    yx = EClass('YX', superclass=(right, left))
    leaf = EClass('Fallback', superclass=(xy, yx))
    assert leaf.python_class.__mro__[:6] == tuple(x.python_class for x in (leaf, xy, yx, left, right, root))
    leaf.eSuperTypes.remove(yx)
    assert leaf.python_class.__mro__[:5] == tuple(x.python_class for x in (leaf, xy, left, right, root))
    assert leaf.python_class.__mro__ == tuple(type.mro(leaf.python_class))


def test_ancestor_update_preserves_descendant_fallback_and_isolation():
    root = EClass('Ancestor')
    parent = EClass('Parent')
    child = EClass('Child', superclass=(root, parent))
    unrelated = EClass('Unrelated')
    original = Metasubinstance.mro
    parent.eSuperTypes.append(root)
    assert child.python_class.__mro__[:3] == tuple(x.python_class for x in (child, root, parent))
    assert isinstance(child(), parent.python_class)
    assert Metasubinstance.mro is original
    assert '_pyecore_alternative_mro' not in unrelated.python_class.__dict__


def test_failed_fallback_restores_local_flags(monkeypatch):
    root, left, right = graph()
    xy = EClass('XY', superclass=(left, right))
    yx = EClass('YX', superclass=(right, left))
    leaf = EClass('Leaf', superclass=xy)
    bases, mro = leaf.python_class.__bases__, leaf.python_class.__mro__
    original = Metasubinstance.mro
    def reject(cls):
        raise RuntimeError('fallback failure')
    monkeypatch.setattr(Metasubinstance, '_mro_alternative', reject)
    with pytest.raises(RuntimeError, match='fallback failure'):
        leaf.eSuperTypes.append(yx)
    assert '_pyecore_alternative_mro' not in leaf.python_class.__dict__
    assert leaf.python_class.__bases__ == bases
    assert leaf.python_class.__mro__ == mro
    assert Metasubinstance.mro is original
    assert EClass('FreshAfterFailure').python_class.__bases__ == (EObject,)
