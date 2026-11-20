from __future__ import annotations

import unittest

from gmt.auth import has_oidc_configuration


class OidcConfigurationTests(unittest.TestCase):
    def test_missing_auth_section_is_not_configured(self) -> None:
        self.assertFalse(has_oidc_configuration({}))

    def test_incomplete_auth_section_is_not_configured(self) -> None:
        self.assertFalse(
            has_oidc_configuration(
                {"auth": {"client_id": "configured", "client_secret": "configured"}}
            )
        )

    def test_complete_auth_section_is_configured(self) -> None:
        self.assertTrue(
            has_oidc_configuration(
                {
                    "auth": {
                        "redirect_uri": "http://localhost:8501/oauth2callback",
                        "cookie_secret": "configured",
                        "client_id": "configured",
                        "client_secret": "configured",
                        "server_metadata_url": "https://issuer.example/.well-known/openid-configuration",
                    }
                }
            )
        )

    def test_empty_auth_value_is_not_configured(self) -> None:
        self.assertFalse(
            has_oidc_configuration(
                {
                    "auth": {
                        "redirect_uri": "",
                        "cookie_secret": "configured",
                        "client_id": "configured",
                        "client_secret": "configured",
                        "server_metadata_url": "https://issuer.example/.well-known/openid-configuration",
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
