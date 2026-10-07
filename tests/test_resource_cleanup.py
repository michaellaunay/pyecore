import io
import pytest
from pyecore.resources import ResourceSet, URI
from pyecore.resources.resource import HttpURI
from pyecore.resources.xmi import XMIResource
from pyecore.resources.json import JsonResource
from pyecore.ecore import EPackage, EClass, EAttribute, EString


class MemoryURI(URI):
    def __init__(self, data=b''):
        super().__init__('memory')
        self.data = data
        self.stream = None

    def create_instream(self):
        self.stream = io.BytesIO(self.data)
        return self.stream

    def create_outstream(self):
        self.stream = io.BytesIO()
        return self.stream

    def close_stream(self):
        if self.stream is not None:
            self.stream.close()


@pytest.mark.parametrize('kind,data', [(XMIResource, b'<broken'),
                                       (JsonResource, b'{broken')])
def test_malformed_closes_and_resets(kind, data):
    uri = MemoryURI(data)
    resource = kind(uri)
    with pytest.raises(Exception):
        resource.load()
    assert uri.stream.closed
    assert not resource.cache_enabled
    assert not resource.contents
    assert not resource.uuid_dict


@pytest.mark.parametrize('kind,data', [
    (XMIResource, b'<p:Thing xmlns:p="urn:cleanup" xmlns:xmi="http://www.omg.org/XMI" xmi:id="id"><unknown/></p:Thing>'),
    (JsonResource, b'{"eClass":"urn:cleanup#//Thing","uuid":"id","unknown":1}')])
def test_partial_load_rollback_and_retry(kind, data):
    pkg = EPackage('cleanup', nsURI='urn:cleanup', nsPrefix='p')
    cls = EClass('Thing'); pkg.eClassifiers.append(cls)
    rset = ResourceSet(); rset.metamodel_registry[pkg.nsURI] = pkg
    uri = MemoryURI(data); resource = kind(uri)
    resource.resource_set = rset
    previous = cls(); resource.append(previous)
    resource.uuid_dict['previous'] = previous
    with pytest.raises(Exception):
        resource.load()
    assert resource.contents == [previous]
    assert resource.uuid_dict == {'previous': previous}
    assert not resource._resolve_mem
    assert not getattr(resource, '_later', [])
    assert not getattr(resource, '_load_href', {})
    assert uri.stream.closed
    uri.data = (b'<p:Thing xmlns:p="urn:cleanup"/>' if kind is XMIResource
                else b'{"eClass":"urn:cleanup#//Thing"}')
    resource.load()
    assert len(resource.contents) == 2


@pytest.mark.parametrize('kind', [XMIResource, JsonResource])
def test_save_error_closes_actual_output(kind, monkeypatch):
    source, target = MemoryURI(), MemoryURI()
    resource = kind(source)
    def fail(*args):
        raise ValueError('serialization failure')
    cls = EClass('Thing'); pkg = EPackage('p', nsURI='urn:p', nsPrefix='p')
    pkg.eClassifiers.append(cls); resource.append(cls())
    monkeypatch.setattr(resource, '_go_across' if kind is XMIResource else 'to_dict', fail)
    with pytest.raises(ValueError):
        resource.save(target)
    assert target.stream.closed


def test_http_stream_closes(monkeypatch):
    stream = io.BytesIO(b'controlled response')
    monkeypatch.setattr('urllib.request.urlopen', lambda url: stream)
    uri = HttpURI('https://example.invalid/model.xmi')
    assert uri.create_instream() is stream
    uri.close_stream()
    assert stream.closed


@pytest.mark.parametrize('kind,extension', [(XMIResource, 'xmi'), (JsonResource, 'json')])
@pytest.mark.parametrize('uuid', [False, True])
def test_semantic_roundtrip(tmp_path, kind, extension, uuid):
    from pyecore.ecore import EReference
    pkg = EPackage('roundtrip', nsURI='urn:roundtrip', nsPrefix='p')
    cls = EClass('Node'); pkg.eClassifiers.append(cls)
    cls.eStructuralFeatures.append(EAttribute('name', EString))
    children = EReference('children', cls, upper=-1, containment=True)
    parent = EReference('parent', cls, eOpposite=children)
    link = EReference('link', cls)
    cls.eStructuralFeatures.extend([children, parent, link])
    rset = ResourceSet(); rset.metamodel_registry[pkg.nsURI] = pkg
    a = rset.create_resource(str(tmp_path / ('a.' + extension)), use_uuid=uuid)
    b = rset.create_resource(str(tmp_path / ('b.' + extension)), use_uuid=uuid)
    root, child, remote = cls(), cls(), cls()
    root.name = 'Été 🌍'; child.name = '子'; remote.name = 'référence'
    root.children.append(child); root.link = remote
    a.append(root); b.append(remote)
    b.save(); a.save()
    original_id = root._internal_id
    loaded = ResourceSet(); loaded.metamodel_registry[pkg.nsURI] = pkg
    result = loaded.get_resource(a.uri).contents[0]
    assert result.name == root.name
    assert result.children[0].name == child.name
    assert result.children[0].parent is result
    assert result.children[0].eContainer() is result
    assert not result.link.resolved
    assert result.link.name == remote.name
    assert result.link.resolved
    if uuid:
        assert result._internal_id == original_id
    loaded.resources[a.uri.normalize()].save()
    again = ResourceSet(); again.metamodel_registry[pkg.nsURI] = pkg
    assert again.get_resource(a.uri).contents[0].link.name == remote.name


def test_xml_entities_and_explicit_parser(tmp_path):
    from lxml.etree import XMLParser, XMLSyntaxError
    from pyecore.resources.xmi import XMIOptions
    pkg = EPackage('p', nsURI='urn:entities', nsPrefix='p')
    cls = EClass('Thing'); cls.eStructuralFeatures.append(EAttribute('name', EString))
    pkg.eClassifiers.append(cls)
    rset = ResourceSet(); rset.metamodel_registry[pkg.nsURI] = pkg
    uri = MemoryURI(b'<!DOCTYPE p:Thing [<!ENTITY value "Unicode: &#233;">]><p:Thing xmlns:p="urn:entities" name="&value;"/>')
    res = XMIResource(uri); res.resource_set = rset; res.load()
    assert res.contents[0].name == 'Unicode: é'
    entity = tmp_path / 'entity.txt'; entity.write_text('controlled é', encoding='utf8')
    uri.data = ('<!DOCTYPE p:Thing [<!ENTITY value SYSTEM "' + entity.as_uri() + '">]><p:Thing xmlns:p="urn:entities"><name>&value;</name></p:Thing>').encode()
    with pytest.raises(XMLSyntaxError):
        res.load()
    res.load({XMIOptions.XML_PARSER: XMLParser(resolve_entities=True, no_network=True)})
    assert res.contents[-1].name == 'controlled é'


@pytest.mark.parametrize('kind,data,extension', [(XMIResource, b'<broken', 'xmi'), (JsonResource, b'{broken', 'json')])
def test_resourceset_removes_failed_resource(tmp_path, kind, data, extension):
    filename = tmp_path / ('bad.' + extension); filename.write_bytes(data)
    rset = ResourceSet()
    with pytest.raises(Exception):
        rset.get_resource(str(filename))
    assert not rset.resources


def test_json_uuid_without_set_features(tmp_path):
    pkg = EPackage('p', nsURI='urn:empty', nsPrefix='p')
    cls = EClass('Empty'); pkg.eClassifiers.append(cls)
    rset = ResourceSet(); rset.metamodel_registry[pkg.nsURI] = pkg
    resource = rset.create_resource(str(tmp_path / 'empty.json'), use_uuid=True)
    obj = cls(); resource.append(obj); resource.save()
    fresh = ResourceSet(); fresh.metamodel_registry[pkg.nsURI] = pkg
    loaded = fresh.get_resource(resource.uri).contents[0]
    assert loaded._internal_id == obj._internal_id
    assert obj._internal_id is not None


def test_failed_xmi_removes_inverse_references():
    from pyecore.ecore import EReference
    pkg = EPackage('p', nsURI='urn:inverse', nsPrefix='p')
    cls = EClass('Thing'); pkg.eClassifiers.append(cls)
    back = EReference('back', cls, upper=-1)
    link = EReference('link', cls, eOpposite=back)
    broken = EReference('broken', cls)
    cls.eStructuralFeatures.extend([back, link, broken])
    uri = MemoryURI(b'<p:Thing xmlns:p="urn:inverse" link="/0" broken="/999"/>')
    res = XMIResource(uri); rset = ResourceSet(); res.resource_set = rset
    rset.metamodel_registry[pkg.nsURI] = pkg
    previous = cls(); res.append(previous)
    with pytest.raises(IndexError):
        res.load()
    assert not previous.back
    assert not previous._inverse_rels


def test_xml_external_dtd_not_loaded():
    from lxml.etree import XMLParser, Resolver
    from pyecore.resources.xmi import XMIOptions
    calls = []
    class ControlledResolver(Resolver):
        def resolve(self, url, public_id, context):
            calls.append(url)
            return self.resolve_string('<!ENTITY value "controlled">', context)
    pkg = EPackage('p', nsURI='urn:dtd', nsPrefix='p')
    cls = EClass('Thing'); pkg.eClassifiers.append(cls)
    uri = MemoryURI(b'<!DOCTYPE p:Thing SYSTEM "https://example.invalid/external.dtd"><p:Thing xmlns:p="urn:dtd"/>')
    resource = XMIResource(uri); resource.resource_set = ResourceSet()
    resource.resource_set.metamodel_registry[pkg.nsURI] = pkg
    resource.load()
    parser = XMLParser(load_dtd=True, no_network=True)
    parser.resolvers.add(ControlledResolver())
    resource.load({XMIOptions.XML_PARSER: parser})
    assert calls == ['https://example.invalid/external.dtd']


def test_http_model_loading_remains_available(monkeypatch):
    streams = []
    def response(url):
        assert url == 'https://example.invalid/model.xmi'
        stream = io.BytesIO(b'<ecore:EPackage xmlns:ecore="http://www.eclipse.org/emf/2002/Ecore" name="remote" nsURI="urn:remote" nsPrefix="r"/>')
        streams.append(stream)
        return stream
    monkeypatch.setattr('urllib.request.urlopen', response)
    resource = ResourceSet().get_resource('https://example.invalid/model.xmi')
    assert resource.contents[0].name == 'remote'
    assert all(s.closed for s in streams)


@pytest.mark.parametrize('kind', [XMIResource, JsonResource])
@pytest.mark.parametrize('operation', ['write', 'flush'])
def test_io_save_failure_closes(kind, operation):
    class BrokenStream(io.BytesIO):
        def write(self, value):
            if operation == 'write':
                raise OSError('write failed')
            return super().write(value)
        def flush(self):
            if operation == 'flush':
                raise OSError('flush failed')
            return super().flush()
    class BrokenURI(MemoryURI):
        def create_outstream(self):
            self.stream = BrokenStream()
            return self.stream
    resource = kind(MemoryURI())
    pkg = EPackage('p', nsURI='urn:p', nsPrefix='p')
    cls = EClass('Thing'); pkg.eClassifiers.append(cls)
    resource.append(cls())
    output = BrokenURI()
    with pytest.raises(OSError):
        resource.save(output)
    assert output.stream.closed
