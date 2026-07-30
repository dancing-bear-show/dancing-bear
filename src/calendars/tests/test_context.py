import os
import unittest
from unittest.mock import patch

from calendars.context import OutlookContext


class TestOutlookContext(unittest.TestCase):
    def test_env_resolution(self):
        old_id = os.environ.get('MAIL_ASSISTANT_OUTLOOK_CLIENT_ID')
        old_tenant = os.environ.get('MAIL_ASSISTANT_OUTLOOK_TENANT')
        try:
            os.environ['MAIL_ASSISTANT_OUTLOOK_CLIENT_ID'] = 'ENV_CLIENT'
            os.environ['MAIL_ASSISTANT_OUTLOOK_TENANT'] = 'common'
            # Mock config resolver to isolate from user's credentials.ini
            with patch('mail.config_resolver.get_outlook_client_id', return_value=None), \
                 patch('mail.config_resolver.get_outlook_tenant', return_value=None), \
                 patch('mail.config_resolver.get_outlook_token_path', return_value=None):
                ctx = OutlookContext()
                cid, ten, tok = ctx.resolve()
                self.assertEqual(cid, 'ENV_CLIENT')
                self.assertEqual(ten, 'common')
                self.assertIsNone(tok)
        finally:
            if old_id is None:
                os.environ.pop('MAIL_ASSISTANT_OUTLOOK_CLIENT_ID', None)
            else:
                os.environ['MAIL_ASSISTANT_OUTLOOK_CLIENT_ID'] = old_id
            if old_tenant is None:
                os.environ.pop('MAIL_ASSISTANT_OUTLOOK_TENANT', None)
            else:
                os.environ['MAIL_ASSISTANT_OUTLOOK_TENANT'] = old_tenant


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

