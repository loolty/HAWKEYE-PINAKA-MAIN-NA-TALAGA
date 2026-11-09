"""SMS tests: phone cleanup and provider calls (network replaced by fakes, nothing is really sent).

    python -m unittest tests.test_sms -v
"""
import io, json, os, sys, unittest, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sms


class _Resp:
    def __init__(self, body, status=200): self.body, self.status = body, status
    def read(self): return self.body.encode()
    def __enter__(self): return self
    def __exit__(self, *a): pass


class SmsTests(unittest.TestCase):
    def setUp(self):
        for k in list(os.environ):
            if k.startswith(('SMS_', 'TWILIO_', 'SEMAPHORE_')): del os.environ[k]
        self.calls = []; self._orig = sms.urllib.request.urlopen
        self.addCleanup(lambda: setattr(sms.urllib.request, 'urlopen', self._orig))

    def fake(self, response):
        def f(req, timeout=None):
            self.calls.append((req.full_url, req.data.decode()))
            if isinstance(response, Exception): raise response
            return response
        sms.urllib.request.urlopen = f

    def test_normalize(self):
        for raw, want in {'09171234567': '+639171234567', '9171234567': '+639171234567', '639171234567': '+639171234567',
                          '+63 917 123 4567': '+639171234567', '0063-917-123-4567': '+639171234567', '+14155552671': '+14155552671',
                          '': None, 'abc': None, '0917123': None, '09171234567890': None}.items():
            self.assertEqual(sms.normalize_phone(raw), want, raw)

    def test_off_by_default_and_never_calls_network(self):
        self.fake(_Resp('{}'))
        ok, detail = sms.send_sms('09171234567', 'hi')
        self.assertFalse(ok); self.assertEqual(self.calls, []); self.assertFalse(sms.is_configured())

    def test_twilio_success_and_failure(self):
        os.environ.update(SMS_PROVIDER='twilio', TWILIO_ACCOUNT_SID='AC1', TWILIO_AUTH_TOKEN='t', TWILIO_FROM_NUMBER='+12025550123')
        self.fake(_Resp(json.dumps({'sid': 'SM1'}), 201))
        self.assertEqual(sms.send_sms('09171234567', 'hello'), (True, 'SMS sent.'))
        self.assertIn('To=%2B639171234567', self.calls[0][1]); self.assertIn('/Accounts/AC1/Messages.json', self.calls[0][0])
        self.fake(urllib.error.HTTPError('u', 401, 'x', {}, io.BytesIO(b'{"message":"Authenticate"}')))
        ok, detail = sms.send_sms('09171234567', 'hello'); self.assertFalse(ok); self.assertIn('login failed', detail)

    def test_semaphore(self):
        os.environ.update(SMS_PROVIDER='semaphore', SEMAPHORE_API_KEY='k')
        self.fake(_Resp(json.dumps([{'message_id': 1, 'status': 'Pending'}])))
        self.assertTrue(sms.send_sms('+639171234567', 'hi')[0]); self.assertIn('number=639171234567', self.calls[0][1])
        self.assertFalse(sms.send_sms('+14155552671', 'hi')[0])      # Semaphore is Philippines-only

    def test_network_error_does_not_raise_and_long_text_is_cut(self):
        os.environ.update(SMS_PROVIDER='semaphore', SEMAPHORE_API_KEY='k')
        self.fake(urllib.error.URLError('down')); self.assertFalse(sms.send_sms('09171234567', 'hi')[0])
        self.fake(_Resp(json.dumps([{'status': 'Pending'}]))); sms.send_sms('09171234567', 'x' * 1000)
        self.assertLessEqual(len(self.calls[-1][1]), 400)

    def test_android_gateway_cloud_and_local(self):
        os.environ.update(SMS_PROVIDER='android', ANDROID_SMS_USER='u', ANDROID_SMS_PASSWORD='p')
        self.fake(_Resp(json.dumps({'id': 'x', 'state': 'Pending'}), 202))
        self.assertTrue(sms.send_sms('09171234567', 'hello')[0])
        url, body = self.calls[-1]
        self.assertEqual(url, 'https://api.sms-gate.app/3rdparty/v1/message')
        self.assertEqual(json.loads(body), {'textMessage': {'text': 'hello'}, 'phoneNumbers': ['+639171234567']})
        os.environ['ANDROID_SMS_URL'] = 'http://192.168.1.50:8080/'
        self.assertTrue(sms.send_sms('09171234567', 'hello')[0]); self.assertEqual(self.calls[-1][0], 'http://192.168.1.50:8080/message')
        self.fake(urllib.error.HTTPError('u', 401, 'x', {}, io.BytesIO(b'{}')))
        ok, detail = sms.send_sms('09171234567', 'hi'); self.assertFalse(ok); self.assertIn('login failed', detail)
        self.fake(urllib.error.URLError('unreachable'))
        ok, detail = sms.send_sms('09171234567', 'hi'); self.assertFalse(ok); self.assertIn('phone gateway', detail)
        os.environ['ANDROID_SMS_URL'] = 'ftp://x'; self.assertFalse(sms.send_sms('09171234567', 'hi')[0])
        del os.environ['ANDROID_SMS_PASSWORD']; self.assertFalse(sms.is_configured())

    def test_demo_mode_records_and_never_touches_the_network(self):
        import tempfile
        sms.DEMO_LOG = os.path.join(tempfile.mkdtemp(), 'sms_demo.log')
        os.environ['SMS_PROVIDER'] = 'demo'; self.fake(_Resp('{}'))
        self.assertTrue(sms.is_configured()); self.assertEqual(sms.channel_label(), 'SMS (demo)')
        ok, detail = sms.send_sms('09171234567', 'Reminder: visit tomorrow')
        self.assertTrue(ok); self.assertIn('not really sent', detail); self.assertEqual(self.calls, [])
        text = open(sms.DEMO_LOG, encoding='utf-8').read(); self.assertIn('Reminder: visit tomorrow', text); self.assertNotIn('09171234567', text)
        self.assertFalse(sms.send_sms('nope', 'x')[0])             # bad numbers are still rejected in demo mode

    def test_traccar_gateway(self):
        os.environ.update(SMS_PROVIDER='traccar', TRACCAR_SMS_TOKEN='tok')
        self.fake(_Resp('{}', 200)); self.assertTrue(sms.send_sms('09171234567', 'hello')[0])
        url, body = self.calls[-1]; self.assertEqual(url, 'https://www.traccar.org/sms/')
        self.assertEqual(json.loads(body), {'to': '+639171234567', 'message': 'hello'})
        self.fake(urllib.error.HTTPError('u', 401, 'x', {}, io.BytesIO(b'denied')))
        ok, detail = sms.send_sms('09171234567', 'hi'); self.assertFalse(ok); self.assertIn('TRACCAR_SMS_TOKEN', detail)
        del os.environ['TRACCAR_SMS_TOKEN']; self.assertFalse(sms.is_configured())


if __name__ == '__main__':
    unittest.main()
