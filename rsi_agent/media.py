"""Turn a source-qualified native export into an actual model image block."""
import base64
import hashlib


class MediaPending(ValueError):
    pass


class MediaUnavailable(ValueError):
    pass


def image_part(transport, server):
    value = transport({'op': 'image', 'server_id': str(server)})
    if value.get('state') == 'media_pending':
        raise MediaPending('The original image export is pending.')
    if value.get('state') != 'image_ready' or value.get('source_verified') is not True:
        raise MediaUnavailable(value.get('code', 'IMAGE_NOT_AVAILABLE'))
    data = base64.b64decode(value['data'], validate=True)
    if not data or hashlib.sha256(data).hexdigest() != value['sha256']:
        raise MediaUnavailable('IMAGE_BYTES_CHANGED')
    if value['mime'] not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
        raise MediaUnavailable('IMAGE_TYPE_UNSUPPORTED')
    return {'type': 'image_url', 'image_url': {'url': 'data:' + value['mime'] + ';base64,' + value['data']}}
