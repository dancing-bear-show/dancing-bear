import os
import unittest

from calendar_assistant.context import OutlookContext


class TestOutlookContext(unittest.TestCase):
    def test_env_resolution(self):
        old_id = os.environ.get('MAIL_ASSISTANT_OUTLOOK_CLIENT_ID')
        old_tenant = os.environ.get('MAIL_ASSISTANT_OUTLOOK_TENANT')
        try:
            os.environ['MAIL_ASSISTANT_OUTLOOK_CLIENT_ID'] = 'ENV_CLIENT'
            os.environ['MAIL_ASSISTANT_OUTLOOK_TENANT'] = 'common'
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

