from unittest import mock

import pytest

from analytics.track import track_request


@pytest.mark.parametrize("request_uri, expected_ga_requests", (
        ("/api/v1/flags/", 2),
        ("/api/v1/identities/", 2),
        ("/api/v1/traits/", 2),
        ("/api/v1/features/", 1),
))
@mock.patch("analytics.track.requests")
@mock.patch("analytics.track.Environment")
def test_track_request(MockEnvironment, mock_requests, request_uri, expected_ga_requests):
    """
    Verify that the correct number of calls are made to GA for the various uris.

    All SDK endpoints should send 2 requests as they send a page view and an event (for managing number of API
    requests made by an organisation). All API requests made to the 'admin' API, for managing flags, etc. should
    only send a page view request.
    """
    # Given
    request = mock.MagicMock()
    request.path = request_uri
    environment_api_key = "test"
    request.headers = {"X-Environment-Key": environment_api_key}

    # When
    track_request(request)

    # Then
    assert mock_requests.post.call_count == expected_ga_requests
