"""Unit tests for the optional GitHub Pages refresh integration."""
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from core.prerender import _dispatch_prerender_refresh, request_prerender_refresh


@override_settings(
    PRERENDER_GITHUB_TOKEN="test-token-not-real",
    PRERENDER_GITHUB_REPOSITORY="andywhite97/sureplace",
    PRERENDER_DISPATCH_COOLDOWN_SECONDS=300,
    PRERENDER_DISPATCH_TIMEOUT_SECONDS=3,
)
class PrerenderDispatchTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("core.prerender.urlopen")
    def test_dispatch_uses_private_auth_header_and_is_throttled(self, urlopen):
        response = MagicMock()
        response.status = 204
        urlopen.return_value.__enter__.return_value = response
        self.assertTrue(_dispatch_prerender_refresh())
        self.assertFalse(_dispatch_prerender_refresh())
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token-not-real")
        self.assertIn("content-published", request.data.decode())

    @patch("core.prerender.urlopen", side_effect=TimeoutError)
    def test_dispatch_failure_releases_cooldown_for_retry(self, urlopen):
        self.assertFalse(_dispatch_prerender_refresh())
        self.assertFalse(_dispatch_prerender_refresh())
        self.assertEqual(urlopen.call_count, 2)

    @override_settings(PRERENDER_GITHUB_REPOSITORY="../outside")
    @patch("core.prerender.urlopen")
    def test_invalid_repository_is_rejected(self, urlopen):
        self.assertFalse(_dispatch_prerender_refresh())
        urlopen.assert_not_called()

    @override_settings(PRERENDER_GITHUB_TOKEN="")
    @patch("core.prerender.urlopen")
    def test_missing_token_disables_dispatch(self, urlopen):
        self.assertFalse(_dispatch_prerender_refresh())
        urlopen.assert_not_called()


@override_settings(PRERENDER_GITHUB_TOKEN="test-token-not-real")
class PrerenderTransactionTests(TestCase):
    @patch("core.prerender._dispatch_prerender_refresh")
    def test_dispatch_only_after_successful_commit(self, dispatch):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            request_prerender_refresh()
            dispatch.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        dispatch.assert_called_once_with()
