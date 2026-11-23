"""Integration tests against a real S3 server.

Unlike the endpoint tests, nothing is faked here: dtool-s3 talks to an S3
server, signed URLs are used over HTTP, and the dataset is registered in
dserver. CI runs these against SeaweedFS (see .github/workflows/test.yml).

They are skipped unless DSERVER_S3_INTEGRATION_TESTS=1. The S3 server must
have a bucket named after the test base URI (``snow-white``) and boto3's
default configuration must point at it, e.g. via AWS_ENDPOINT_URL,
AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.
"""

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid as uuid_module
from urllib.parse import quote

import pytest

from .conftest import BASE_URI, auth_header

pytestmark = pytest.mark.skipif(
    os.environ.get("DSERVER_S3_INTEGRATION_TESTS") != "1",
    reason="set DSERVER_S3_INTEGRATION_TESTS=1 to run against an S3 server",
)

BUCKET = BASE_URI[len("s3://"):]
UPLOAD_ROUTE = f"/signed-urls/upload/{quote(BASE_URI, safe='')}"
README = "---\ndescription: Grüße aus dem Integrationstest\n"
ITEMS = {
    "data.txt": b"hello from the integration test\n",
    "nested/dir/values.bin": bytes(range(256)) * 4,
}


def _http(method, url, data=None, headers=None):
    """Return (status, body) of an HTTP request to a signed URL."""
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


@pytest.fixture
def dataset_uuid():
    """Fresh dataset UUID; removes everything stored for it afterwards."""
    import boto3

    dataset_uuid = str(uuid_module.uuid4())
    yield dataset_uuid

    bucket = boto3.resource("s3").Bucket(BUCKET)
    keys = [obj.key for obj in bucket.objects.all()
            if dataset_uuid in obj.key]
    for i in range(0, len(keys), 500):
        bucket.delete_objects(Delete={
            "Objects": [{"Key": key} for key in keys[i:i + 500]]})


def _upload_request(dataset_uuid):
    return {
        "uuid": dataset_uuid,
        "name": "integration-dataset",
        "creator_username": "grumpy",
        "frozen_at": 1700000000.0,
        "hash_function": "md5sum_hexdigest",
        "items": [
            {
                "relpath": relpath,
                "size_in_bytes": len(content),
                "hash": hashlib.md5(content).hexdigest(),
                "utc_timestamp": 1700000000.0,
            }
            for relpath, content in ITEMS.items()
        ],
        "tags": ["integration"],
        "annotations": {"project": "s3-ci"},
        "overlays": {},
    }


def _initiate_upload(client, token, dataset_uuid):
    response = client.post(
        UPLOAD_ROUTE, json=_upload_request(dataset_uuid),
        headers=auth_header(token))
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _put_item(item_url, content):
    return _http("PUT", item_url["url"], data=content,
                 headers=item_url["headers"])


def test_upload_and_read_back(client, grumpy_token, dataset_uuid):
    import dtoolcore
    from dtoolcore.utils import generate_identifier

    upload = _initiate_upload(client, grumpy_token, dataset_uuid)
    uri = upload["uri"]
    assert uri == f"{BASE_URI}/{dataset_uuid}"

    # The client uploads README and items directly to S3.
    status, body = _http("PUT", upload["upload_urls"]["readme"],
                         data=README.encode("utf-8"))
    assert status == 200, body
    item_urls = upload["upload_urls"]["items"]
    for relpath, content in ITEMS.items():
        status, body = _put_item(
            item_urls[generate_identifier(relpath)], content)
        assert status == 200, body

    response = client.post(
        "/signed-urls/upload-complete", json={"uri": uri},
        headers=auth_header(grumpy_token))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["status"] == "registered"

    # The dataset in S3 is frozen with the client's hashes.
    dataset = dtoolcore.DataSet.from_uri(uri)
    assert dataset.admin_metadata["type"] == "dataset"
    assert dataset.admin_metadata["frozen_at"] == 1700000000.0
    assert dataset.get_readme_content() == README
    assert dataset.list_tags() == ["integration"]
    assert dataset.get_annotation("project") == "s3-ci"
    assert set(dataset.identifiers) == {
        generate_identifier(relpath) for relpath in ITEMS}
    for relpath, content in ITEMS.items():
        properties = dataset.item_properties(generate_identifier(relpath))
        assert properties["relpath"] == relpath
        assert properties["hash"] == hashlib.md5(content).hexdigest()
        assert properties["size_in_bytes"] == len(content)

    # dserver registered it.
    response = client.get(
        f"/readmes/{quote(uri, safe='')}", headers=auth_header(grumpy_token))
    assert response.status_code == 200, response.get_data(as_text=True)

    # Reading back through the signed read URLs returns the uploaded data.
    response = client.get(
        f"/signed-urls/dataset/{quote(uri, safe='')}",
        headers=auth_header(grumpy_token))
    assert response.status_code == 200, response.get_data(as_text=True)
    urls = response.get_json()
    status, body = _http("GET", urls["readme_url"])
    assert status == 200 and body.decode("utf-8") == README
    status, body = _http("GET", urls["admin_metadata_url"])
    assert status == 200 and json.loads(body)["uuid"] == dataset_uuid
    for relpath, content in ITEMS.items():
        status, body = _http(
            "GET", urls["item_urls"][generate_identifier(relpath)])
        assert status == 200 and body == content

    # Signed URLs of a single item work as well.
    identifier = generate_identifier("data.txt")
    response = client.get(
        f"/signed-urls/item/{quote(uri, safe='')}/{identifier}",
        headers=auth_header(grumpy_token))
    assert response.status_code == 200, response.get_data(as_text=True)
    status, body = _http("GET", response.get_json()["url"])
    assert status == 200 and body == ITEMS["data.txt"]


def test_upload_with_wrong_content_is_rejected_by_s3(
        client, grumpy_token, dataset_uuid):
    """Item upload URLs pin the MD5 announced by the client. S3 must reject
    content that does not match, so that the hashes in the manifest (which
    are trusted on upload-complete) describe what is actually stored."""
    from dtoolcore.utils import generate_identifier

    upload = _initiate_upload(client, grumpy_token, dataset_uuid)
    item_url = upload["upload_urls"]["items"][generate_identifier("data.txt")]
    assert "Content-MD5" in item_url["headers"]

    status, _ = _put_item(item_url, b"tampered content")
    assert status >= 400

    # The pinned headers cannot simply be replaced: they are signed.
    headers = dict(item_url["headers"])
    headers["Content-MD5"] = base64.b64encode(
        hashlib.md5(b"tampered content").digest()).decode()
    status, _ = _http("PUT", item_url["url"], data=b"tampered content",
                      headers=headers)
    assert status >= 400

    # The correct content is accepted.
    status, body = _put_item(item_url, ITEMS["data.txt"])
    assert status == 200, body
