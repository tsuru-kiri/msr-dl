from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from monster_siren.api import MonsterSirenAPI, MonsterSirenAPIError


class APITests(unittest.TestCase):
    @staticmethod
    def _response(payload: object) -> Mock:
        response = Mock()
        response.is_redirect = False
        response.headers = {}
        response.iter_content.return_value = [json.dumps(payload).encode("utf-8")]
        return response

    def test_application_error_is_not_returned_as_data(self) -> None:
        api = MonsterSirenAPI()
        response = self._response({"code": 104, "msg": "not found", "data": {}})
        api.session.get = Mock(return_value=response)

        with self.assertRaisesRegex(MonsterSirenAPIError, "104"):
            api.get_album_detail("missing")
        api.close()

    def test_album_response_shape_is_validated(self) -> None:
        api = MonsterSirenAPI()
        response = self._response({"code": 0, "msg": "", "data": {}})
        api.session.get = Mock(return_value=response)

        with self.assertRaisesRegex(ValueError, "must be a list"):
            api.get_albums()
        api.close()

    def test_untrusted_download_url_is_rejected(self) -> None:
        api = MonsterSirenAPI()
        with self.assertRaisesRegex(ValueError, "Untrusted"):
            api.download_bytes("http://127.0.0.1/secret", max_bytes=100)
        api.close()

    def test_redirect_target_is_validated_before_following(self) -> None:
        api = MonsterSirenAPI()
        response = Mock()
        response.is_redirect = True
        response.headers = {"location": "http://127.0.0.1/secret"}
        api.session.get = Mock(return_value=response)

        with self.assertRaisesRegex(ValueError, "Untrusted"):
            api.download_bytes(
                "https://web.hycdn.cn/redirect",
                max_bytes=100,
            )
        self.assertEqual(api.session.get.call_count, 1)
        api.close()


if __name__ == "__main__":
    unittest.main()
