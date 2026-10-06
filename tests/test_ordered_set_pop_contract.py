import pytest
from pyecore.ecore import OrderedSet, EPackage, EClass, EReference
from pyecore.notification import EObserver, Kind


def assert_positions(collection, expected):
    assert list(collection) == expected
    assert collection.map == {value: i for i, value in enumerate(expected)}
    for i, value in enumerate(expected):
        assert collection.index(value) == i
        assert collection[i] == value


@pytest.mark.parametrize('values', [[-1, 0, 2], [0, -1, 2], [0, 2, -1], [7]])
@pytest.mark.parametrize('index', [0, 1, 2, -1, -2, -3])
def test_pop_positions(values, index):
    actual = OrderedSet(values)
    expected = list(values)
    if -len(values) <= index < len(values):
        assert actual.pop(index) == expected.pop(index)
    else:
        with pytest.raises(IndexError):
            actual.pop(index)
    assert_positions(actual, expected)
    actual.add(9)
    assert_positions(actual, expected + [9])


@pytest.mark.parametrize('index', [-4, 3, 100])
@pytest.mark.parametrize('operation', ['pop', 'replace'])
def test_invalid_index_atomic(index, operation):
    actual = OrderedSet([-1, 0, 2])
    with pytest.raises(IndexError):
        if operation == 'pop':
            actual.pop(index)
        else:
            actual[index] = 9
    assert_positions(actual, [-1, 0, 2])


@pytest.mark.parametrize('index', [-1, 0, 100])
def test_empty_pop_keeps_keyerror(index):
    with pytest.raises(KeyError):
        OrderedSet().pop(index)


@pytest.mark.parametrize('index', [0, 1, 2, -1, -2, -3])
@pytest.mark.parametrize('replacement', [-1, 0, 2, 9])
def test_replacement_and_duplicates(index, replacement):
    actual = OrderedSet([-1, 0, 2, -1, 0])
    expected = [-1, 0, 2]
    position = index % len(expected)
    expected.pop(position)
    if replacement not in expected:
        expected.insert(position, replacement)
    actual[index] = replacement
    assert_positions(actual, expected)
    actual.insert(0, replacement)
    actual.add(replacement)
    assert_positions(actual, expected)


@pytest.mark.parametrize('index', [0, 1, 2, -1, -2, -3, -4, 3])
@pytest.mark.parametrize('operation', ['pop', 'replace'])
def test_reference_collection_contract(index, operation):
    owner = EPackage('owner')
    values = [EClass(name) for name in ('A', 'B', 'C')]
    owner.eClassifiers.extend(values)
    collection = owner.eClassifiers
    replacement = EClass('D')
    events = []
    EObserver(owner, notifyChanged=events.append)
    expected = list(values)
    if -3 <= index < 3:
        removed = expected.pop(index)
        if operation == 'pop':
            assert collection.pop(index) is removed
        else:
            expected.insert(index % 3, replacement)
            collection[index] = replacement
        assert removed.eContainer() is None
        assert removed.ePackage is None
        assert events[0].kind is Kind.REMOVE
        assert events[0].old is removed
        assert events[0].feature is EPackage.eClassifiers
        assert len(events) == (1 if operation == 'pop' else 2)
        if operation == 'replace':
            assert events[1].kind is Kind.ADD
            assert events[1].new is replacement
    else:
        with pytest.raises(IndexError):
            if operation == 'pop':
                collection.pop(index)
            else:
                collection[index] = replacement
        assert events == []
        assert replacement.eContainer() is None
        assert replacement.ePackage is None
    assert_positions(collection, expected)
    for value in expected:
        assert value.eContainer() is owner
        assert value.ePackage is owner
        assert value.eContainmentFeature() is EPackage.eClassifiers


def test_pop_index_protocol_and_type_error_atomic():
    class Index:
        def __index__(self):
            return -2

    actual = OrderedSet([-1, 0, 2])
    for index in (1.5, '1', slice(None)):
        with pytest.raises(TypeError):
            actual.pop(index)
        assert_positions(actual, [-1, 0, 2])
    assert actual.pop(Index()) == 0
    assert_positions(actual, [-1, 2])


def test_pop_noncontainment_inverse_relations():
    node = EClass('Node')
    refs = EReference('refs', node, upper=-1)
    node.eStructuralFeatures.append(refs)
    owner, first, last = node(), node(), node()
    owner.refs.extend([first, last])
    assert (owner, refs) in last._inverse_rels
    assert owner.refs.pop(-1) is last
    assert (owner, refs) not in last._inverse_rels
    assert (owner, refs) in first._inverse_rels
    assert_positions(owner.refs, [first])
