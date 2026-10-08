"""Opposite references must not duplicate objects/proxies during JSON load."""
import pytest
from pyecore.ecore import EPackage, EClass, EReference, EAttribute, EString, EProxy
from pyecore.resources import ResourceSet
from pyecore.resources.json import JsonResource


@pytest.fixture
def model():
    package = EPackage('opposites', nsURI='urn:json:opposites', nsPrefix='p')
    root, association, end = EClass('Root'), EClass('Association'), EClass('End')
    package.eClassifiers.extend([root, association, end])
    root.eStructuralFeatures.append(EReference('associations', association, upper=-1, containment=True))
    end.eStructuralFeatures.append(EAttribute('name', EString))
    owned = EReference('owned', end, upper=-1, containment=True)
    member = EReference('member', end, upper=-1)
    back = EReference('association', association, eOpposite=member)
    association.eStructuralFeatures.extend([member, owned])
    end.eStructuralFeatures.append(back)
    return package, root, association, end


def resources(package):
    rset = ResourceSet()
    rset.metamodel_registry[package.nsURI] = package
    rset.resource_factory['json'] = JsonResource
    return rset


def resolved(value):
    return value.force_resolve() if isinstance(value, EProxy) else value


@pytest.mark.parametrize('extension', ['json', 'xmi'])
@pytest.mark.parametrize('uuid', [False, True])
@pytest.mark.parametrize('back_many', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_contained_opposite_order_uniqueness(tmp_path, model, extension, uuid, back_many, reverse):
    package, root, association, end = model
    end.findEStructuralFeature('association').upperBound = -1 if back_many else 1
    container, obj = root(), association()
    ends = [end(name='first'), end(name='second')]
    obj.owned.extend(ends)
    expected = ends[::-1] if reverse else ends
    obj.member.extend(expected)
    container.associations.append(obj)
    assert len(obj.owned) == len(obj.member) == 2
    resource = resources(package).create_resource(str(tmp_path / ('model.' + extension)), use_uuid=uuid)
    resource.append(container)
    resource.save()
    ids = [x._internal_id for x in (container, obj, *ends)]
    loaded = resources(package).get_resource(resource.uri).contents[0]
    result = loaded.associations[0]
    members = [resolved(x) for x in result.member]
    assert len(result.owned) == len(members) == len(set(members)) == 2
    assert members == list(result.owned)[::-1 if reverse else 1]
    for item in members:
        assert item.eContainer() is result
        assert item.eContainmentFeature().name == 'owned'
        if back_many:
            assert [resolved(x) for x in item.association] == [result]
        else:
            assert resolved(item.association) is result
    if uuid:
        assert [x._internal_id for x in (loaded, result, *result.owned)] == ids


def test_json_no_opposite_remains_lazy(tmp_path, model):
    package, root, association, end = model
    link = EReference('link', end)
    association.eStructuralFeatures.append(link)
    container, obj, target = root(), association(), end(name='target')
    obj.owned.append(target)
    obj.link = target
    container.associations.append(obj)
    resource = resources(package).create_resource(str(tmp_path / 'plain.json'))
    resource.append(container)
    resource.save()
    loaded = resources(package).get_resource(resource.uri).contents[0].associations[0]
    assert isinstance(loaded.link, EProxy)
    assert not loaded.link.resolved
    assert resolved(loaded.link) is loaded.owned[0]


def test_json_external_opposite_resolution(tmp_path, model):
    package, root, association, end = model
    container, obj, remote = root(), association(), end(name='remote')
    obj.member.append(remote)
    container.associations.append(obj)
    rset = resources(package)
    local = rset.create_resource(str(tmp_path / 'local.json'))
    external = rset.create_resource(str(tmp_path / 'external.json'))
    local.append(container)
    external.append(remote)
    external.save()
    local.save()
    loaded_set = resources(package)
    loaded = loaded_set.get_resource(local.uri).contents[0].associations[0]
    # Updating an opposite already resolves external proxies in the runtime.
    assert len(set(loaded_set.resources.values())) == 2
    assert loaded.member[0].name == 'remote'
    assert resolved(loaded.member[0].association) is loaded
    assert len(loaded.member) == 1


def test_json_nonunique_opposite_preserves_explicit_multiplicity(tmp_path, model):
    package, root, association, end = model
    association.findEStructuralFeature('member').unique = False
    container, obj = root(), association()
    first, second = end(name='first'), end(name='second')
    obj.owned.extend([first, second])
    obj.member.extend([second, first, second])
    container.associations.append(obj)
    resource = resources(package).create_resource(str(tmp_path / 'nonunique.json'))
    resource.append(container)
    resource.save()
    loaded = resources(package).get_resource(resource.uri).contents[0].associations[0]
    assert [resolved(x) for x in loaded.member] == [loaded.owned[1], loaded.owned[0], loaded.owned[1]]


def test_json_opposite_failure_rolls_back_and_retries(tmp_path, model):
    import json
    package, root, association, end = model
    container, obj = root(), association()
    obj.owned.extend([end(name='first'), end(name='second')])
    obj.member.extend(obj.owned)
    container.associations.append(obj)
    path = tmp_path / 'retry.json'
    initial = resources(package).create_resource(str(path), use_uuid=True)
    initial.append(container)
    initial.save()
    valid = path.read_bytes()
    invalid = json.loads(valid)
    invalid['associations'][0]['member'][0]['$ref'] = '/999'
    path.write_text(json.dumps(invalid))
    resource = resources(package).create_resource(str(path))
    with pytest.raises(IndexError):
        resource.load()
    assert resource.contents == []
    assert resource.uuid_dict == {}
    assert resource._load_href == {}
    assert resource._resolve_mem == {}
    assert not resource.cache_enabled
    path.write_bytes(valid)
    resource.load()
    loaded = resource.contents[0].associations[0]
    assert [resolved(x) for x in loaded.member] == list(loaded.owned)
    assert len(loaded.member) == 2
    assert loaded._internal_id == obj._internal_id


def test_json_many_to_many_preserves_both_serialized_orders(tmp_path, model):
    package, root, association, end = model
    back = end.findEStructuralFeature('association')
    back.upperBound = -1
    association.eStructuralFeatures.append(EAttribute('name', EString))
    root.eStructuralFeatures.append(EReference('ends', end, upper=-1, containment=True))
    container = root()
    a, b = association(name='a'), association(name='b')
    x, y = end(name='x'), end(name='y')
    container.associations.extend([a, b])
    container.ends.extend([x, y])
    a.member.extend([x, y])
    b.member.extend([y, x])
    x.association = [b, a]
    forward = [[e.name for e in obj.member] for obj in (a, b)]
    backward = [[obj.name for obj in e.association] for e in (x, y)]
    resource = resources(package).create_resource(str(tmp_path / 'many.json'))
    resource.append(container)
    resource.save()
    loaded = resources(package).get_resource(resource.uri).contents[0]
    assert [[e.name for e in obj.member] for obj in loaded.associations] == forward
    assert [[obj.name for obj in e.association] for e in loaded.ends] == backward
