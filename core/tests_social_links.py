from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from core.social_links import (
    validate_facebook_url,
    validate_instagram_url,
    validate_tiktok_url,
)


class BusinessSocialLinksTests(SimpleTestCase):
    def test_valid_https_links(self):
        for validator, url in (
            (validate_facebook_url, "https://www.facebook.com/sample.business"),
            (validate_instagram_url, "https://instagram.com/sample_business/"),
            (validate_tiktok_url, "https://www.tiktok.com/@samplebusiness"),
        ):
            validator(url)
            validator("")

    def test_invalid_or_unsafe_social_links(self):
        for validator, url in (
            (validate_facebook_url, "http://facebook.com/sample"),
            (validate_facebook_url, "https://facebook.com.evil.example/sample"),
            (validate_facebook_url, "https://evil.example@facebook.com/sample"),
            (validate_instagram_url, "javascript:alert(1)"),
            (validate_instagram_url, "https://instagram.com:8080/sample"),
            (validate_tiktok_url, "https://tiktok.com.evil.example/@fake"),
            (validate_tiktok_url, "https://localhost/@fake"),
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                validator(url)
