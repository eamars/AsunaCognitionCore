"""A model or embedding address is checked as DSH's Models page checks a provider: an http or https URL with a host.
Nothing more: a cloud provider by host name is as valid as a server on this network."""
import pytest

from asuna.config import validate_endpoint


@pytest.mark.parametrize('url', ['http://192.0.2.10:1919/v1', 'https://api.example.com', 'http://localhost:8080/v1',
                                 'https://api.example.com/v1?x=1'])
def test_an_http_or_https_url_with_a_host_is_accepted(url):
    validate_endpoint(url)


@pytest.mark.parametrize('url', ['', 'api.example.com', 'ftp://example.com', 'http://', 'http://example.com:port',
                                 None])
def test_anything_else_is_refused(url):
    with pytest.raises(ValueError, match='INVALID_ENDPOINT'):
        validate_endpoint(url)
