from copy import deepcopy
import base64

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.addon_catalog import Catalog
from backend.media import MAX_IMAGE_BYTES, MediaCache, image_type, validate_url
from backend.media_routes import router

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6YQAAAABJRU5ErkJggg==')


def test_registered_icon_is_same_origin_and_cached_across_restart(tmp_path):
    requests = []
    def fetch(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    media = MediaCache(tmp_path, transport=httpx.MockTransport(fetch))
    url = media.item_icon({'icon': 135274, 'name': '破损的短剑'})
    assert url == '/api/media/wow-icon-135274?size=thumb'
    file, mime = media.get('wow-icon-135274')
    assert file.read_bytes() == PNG and mime == 'image/png'
    def offline(request):
        raise AssertionError('cached artwork must not request the network')
    restarted = MediaCache(tmp_path, transport=httpx.MockTransport(offline))
    assert restarted.get('wow-icon-135274', 'full')[0].read_bytes() == PNG
    assert requests == ['https://wuxianwow.com/share/135274.jpg']


@pytest.mark.parametrize('url', [
    'http://wuxianwow.com/share/135274.jpg',
    'https://evil.example/share/135274.jpg',
    'https://wuxianwow.com:8443/share/135274.jpg',
    'https://user@wuxianwow.com/share/135274.jpg',
    'https://wuxianwow.com/share/../data/135274.jpg',
    'https://wuxianwow.com/share/%2e%2e/data/135274.jpg',
    'https://wuxianwow.com/share/135274.jpg?redirect=http://127.0.0.1',
    'https://wuxianwow.com/share/135274.svg',
])
def test_media_source_allowlist(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_no_public_arbitrary_url_or_unregistered_image(tmp_path):
    media = MediaCache(tmp_path)
    assert media.item_icon({'icon_url': 'https://evil.example/pixel.png'}) is None
    assert media.item_icon({'icon': True}) is None
    assert media.item_icon({'icon': '../file'}) is None
    with pytest.raises(ValueError):
        media.get('135274')
    with pytest.raises(ValueError):
        media.get('../data')
    media.register('test-icon', 'https://wuxianwow.com/share/135274.jpg')
    with pytest.raises(ValueError, match='其他来源'):
        media.register('test-icon', 'https://wuxianwow.com/share/132538.jpg')


def test_redirect_html_and_oversized_downloads_never_cached(tmp_path):
    for index, response in enumerate([
        httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}),
        httpx.Response(200, headers={'Content-Type': 'text/html'}, text='<html>unavailable</html>'),
        httpx.Response(200, headers={'Content-Type': 'image/png'}, content=b'x' * (MAX_IMAGE_BYTES + 1)),
        httpx.Response(200, headers={'Content-Type': 'image/svg+xml'}, text='<svg onload="alert(1)"/>'),
    ]):
        called = []
        def respond(request):
            called.append(request.url)
            return response
        media = MediaCache(tmp_path / str(index), transport=httpx.MockTransport(respond))
        media.item_icon({'icon': 135274})
        with pytest.raises(ValueError):
            media.get('wow-icon-135274')
        assert len(called) == 1
        assert not list((media.root / 'files').iterdir())


def test_packaged_assets_have_thumbnails_and_dynamic_character_identity(tmp_path):
    media = MediaCache(tmp_path)
    mage = media.character_art('MAGE', 'Scourge')
    warrior = media.character_art('WARRIOR', 'Human')
    assert mage['class']['url'] != warrior['class']['url']
    assert mage['race']['url'] != warrior['race']['url']
    assert media.character_art('UNKNOWN', 'Skyborne')['race']['url'] is None
    for ident in media.assets:
        full, mime = media.get(ident, 'full')
        thumb, thumb_mime = media.get(ident)
        assert full.is_file() and thumb.is_file()
        assert mime.startswith('image/') and thumb_mime.startswith('image/')
    assert media.get('ellesmere-preview')[0] != media.get('ellesmere-preview', 'full')[0]
    assert '布局示意' in media.metadata('forever-layout')['caption']
    with pytest.raises(ValueError):
        image_type(b'<html>error</html>')


class Inventory:
    def inventory(self):
        return {'packages': deepcopy([
            {'id': 'dbm', 'name': 'DBM', 'version': '1', 'managed': True, 'source': 'github',
             'modules': [{'directory': 'DBM-Core', 'dependencies': [], 'metadata': {'author': 'MysticalOS'}}],
             'update': {'status': 'release_differs', 'checked_at': 100, 'release': {'version': '2'}}},
            {'id': 'local-Unknown', 'name': 'Unknown', 'version': None, 'managed': False, 'source': 'unbound',
             'modules': [{'directory': 'Unknown', 'dependencies': [], 'metadata': {}}]},
        ]), 'diagnostics': [], 'errors': [], 'module_count': 2}


def test_catalog_is_specific_projects_and_preserves_inventory_facts(tmp_path):
    media = MediaCache(tmp_path)
    catalog = Catalog(Inventory(), media)
    inventory = catalog.inventory()
    assert inventory['module_count'] == 2
    assert inventory['packages'][0]['available_version'] == '2'
    assert inventory['packages'][0]['author'] == 'MysticalOS'
    unknown = inventory['packages'][1]
    assert unknown['icon_url'] == '/api/media/category-addon?size=thumb'
    assert unknown['available_version'] is None and unknown['recognized'] is False
    browse = catalog.browse()
    assert not {'bags', 'maps', 'combat', 'suite'} & {i['id'] for i in browse['items']}
    assert 'littlewigs' in [i['id'] for i in catalog.browse('LittleWigs')['items']]
    assert all(i['category'] == '副本' for i in catalog.browse(category='副本')['items'])
    assert catalog.detail('littlewigs')['dependencies'] == ['BigWigs']
    assert catalog.detail('dbm')['screenshots'][0]['source_url'].startswith('https://media.forgecdn.net/')
    assert catalog.profile_media('ForeverUI')['kind'] == 'layout_diagram'
    assert catalog.detail('local-Unknown')['author'] == '作者未注明'
    with pytest.raises(ValueError):
        catalog.detail('nonexistent')


def test_catalog_and_media_routes_are_read_only(tmp_path):
    media = MediaCache(tmp_path)
    app = FastAPI()
    app.include_router(router(Catalog(Inventory(), media), media))
    with TestClient(app) as client:
        assert client.get('/api/catalog?q=Details').json()['total'] == 1
        response = client.get('/api/media/ellesmere-icon')
        assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
        assert client.get('/api/media/unregistered').status_code == 404
        assert client.get('/api/media/ellesmere-icon?size=../../').status_code == 404
        assert client.post('/api/media/anything', json={'url': 'https://evil.example'}).status_code == 405
        assert client.get('/api/catalog/dbm').json()['available_version'] == '2'
