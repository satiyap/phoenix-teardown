"""Executable negative controls for the Ory-only northbound authentication contract."""
from __future__ import annotations

import copy
import unittest

import yaml

import validate_spec


BASE = yaml.safe_load((validate_spec.SPEC / "contracts" / "openapi.yaml").read_text())


class OryContractTests(unittest.TestCase):
    def test_current_contract(self):
        self.assertEqual(validate_spec.check_ory_auth_contract(BASE), [])

    def test_retired_exchange_and_discovery_cannot_return(self):
        for path in ("/v1/auth/discover", "/v1/auth/exchange", "/v1/identity-providers"):
            with self.subTest(path=path):
                doc = copy.deepcopy(BASE)
                doc["paths"][path] = {"post": {"security": []}}
                self.assertTrue(any("retired" in error for error in validate_spec.check_ory_auth_contract(doc)))

    def test_duplicate_cookie_does_not_replace_machine_admins(self):
        doc = copy.deepcopy(BASE)
        doc["security"] = [{"agentToken": []}, {"orySession": []}, {"orySession": []}]
        self.assertTrue(any("once each" in error for error in validate_spec.check_ory_auth_contract(doc)))

    def test_human_session_cannot_become_a_bearer_scheme(self):
        doc = copy.deepcopy(BASE)
        doc["components"]["securitySchemes"]["orySession"] = {"type": "http", "scheme": "bearer"}
        self.assertTrue(any("session cookie" in error for error in validate_spec.check_ory_auth_contract(doc)))

    def test_machine_admin_cannot_replace_human_authority(self):
        for method, path in (
            ("get", "/v1/auth/session"), ("get", "/v1/tenants"),
            ("get", "/v1/tenants/{id}/provisioning"), ("post", "/v1/teams"),
            ("put", "/v1/teams/{id}/members/{principal_id}"),
            ("post", "/v1/teams/{id}/members/{principal_id}/remove"),
        ):
            with self.subTest(path=path):
                doc = copy.deepcopy(BASE)
                doc["paths"][path][method]["security"] = [{"adminToken": []}]
                self.assertTrue(any("only orySession" in error for error in validate_spec.check_ory_auth_contract(doc)))

    def test_operator_authority_is_not_tenant_administration(self):
        doc = copy.deepcopy(BASE)
        doc["paths"]["/v1/tenants"]["get"]["x-phoenix-authority"] = "tenant-admin"
        self.assertTrue(any("platform-operator authority" in error for error in validate_spec.check_ory_auth_contract(doc)))

    def test_new_anonymous_northbound_route_is_refused(self):
        doc = copy.deepcopy(BASE)
        doc["paths"]["/v1/agents"]["get"]["security"] = []
        self.assertTrue(any("anonymous northbound" in error for error in validate_spec.check_ory_auth_contract(doc)))


if __name__ == "__main__":
    unittest.main()
