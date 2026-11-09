"""SMS + Profile/Security flow tests. Needs the same throwaway MySQL "_test" database as test_two_step_google:

    set MYSQL_DATABASE=hawkeyes_test
    python -m unittest tests.test_sms_flow -v
"""
import unittest
from tests.test_two_step_google import A, make_user, password_login, post, sql, row, reset_limits


class SmsAndProfile(unittest.TestCase):
    def setUp(self):
        reset_limits()
        self.sent = []; self.sms_result = (True, 'SMS sent.'); self.mail_result = (True, 'ok')
        self._orig = (A.sms.send_sms, A.send_email, A.sms.is_configured)
        A.sms.send_sms = lambda phone, msg: (self.sent.append(('sms', phone, msg)) or self.sms_result)
        A.send_email = lambda to, subj, html, text=None: (self.sent.append(('email', to, subj)) or self.mail_result)
        A.sms.is_configured = lambda: True
        self.addCleanup(lambda: (setattr(A.sms, 'send_sms', self._orig[0]), setattr(A, 'send_email', self._orig[1]), setattr(A.sms, 'is_configured', self._orig[2])))

    # ---- Profile / Security ----
    def test_patient_profile_contains_security_and_nav_has_no_security_tab(self):
        uid, pw = make_user('prof1@example.test'); c = A.app.test_client(); password_login(c, 'prof1@example.test', pw)
        html = c.get('/patient/profile').get_data(as_text=True)
        self.assertIn('id="security"', html); self.assertIn('Two-step sign-in', html)
        self.assertNotIn('>Security</a>', html)
        r = c.get('/account/security'); self.assertTrue(r.headers['Location'].endswith('/patient/profile#security'))

    def test_staff_keep_the_standalone_security_page(self):
        sid, pw = make_user('prof2@example.test', role='Clinic Staff', name='Clerk'); c = A.app.test_client(); password_login(c, 'prof2@example.test', pw, patient=False)
        self.assertEqual(c.get('/account/security').status_code, 200)

    def test_profile_phone_validation_and_save(self):
        uid, pw = make_user('prof3@example.test'); c = A.app.test_client(); password_login(c, 'prof3@example.test', pw)
        post(c, '/patient/profile', '/patient/profile', phone='hello', address='x', channel='SMS', email='evil@example.test')
        self.assertIsNone(row('SELECT phone FROM patients WHERE user_id=?', (uid,))['phone'])
        post(c, '/patient/profile', '/patient/profile', phone='', address='x', channel='SMS')            # SMS needs a number
        self.assertNotEqual(row('SELECT channel FROM patients WHERE user_id=?', (uid,))['channel'], 'SMS')
        post(c, '/patient/profile', '/patient/profile', phone='0917 123 4567', address='Manila', channel='SMS', email='evil@example.test')
        r = row('SELECT phone,channel,email FROM patients WHERE user_id=?', (uid,))
        self.assertEqual((r['phone'], r['channel']), ('0917 123 4567', 'SMS')); self.assertEqual(r['email'], 'prof3@example.test')   # email is not editable

    # ---- notify_patient channel logic ----
    def test_sms_preferred_sends_sms_only(self):
        via, d, label, status = A.notify_patient('a@b.test', '09171234567', 'SMS', 's', '<p>h</p>', 't', 'sms text')
        self.assertEqual((via, label, status), (['SMS'], 'SMS + Website', 'Sent')); self.assertEqual([k for k, *_ in self.sent], ['sms'])

    def test_sms_failure_falls_back_to_email(self):
        self.sms_result = (False, 'nope')
        via, d, label, status = A.notify_patient('a@b.test', '09171234567', 'SMS', 's', '<p>h</p>', 't', 'x')
        self.assertEqual((via, label, status), (['Email'], 'Email + Website', 'Sent')); self.assertEqual([k for k, *_ in self.sent], ['sms', 'email'])

    def test_email_preferred_does_not_text_unless_email_fails(self):
        via, *_ = A.notify_patient('a@b.test', '09171234567', 'Email', 's', 'h', 't', 'x'); self.assertEqual((via, [k for k, *_ in self.sent]), (['Email'], ['email']))
        self.sent.clear(); self.mail_result = (False, 'smtp down')
        via, d, label, status = A.notify_patient('a@b.test', '09171234567', 'Email', 's', 'h', 't', 'x')
        self.assertEqual((via, status), (['SMS'], 'Sent')); self.assertEqual([k for k, *_ in self.sent], ['email', 'sms'])

    def test_everything_failing_and_nothing_on_file(self):
        self.sms_result = (False, 'a'); self.mail_result = (False, 'b')
        self.assertEqual(A.notify_patient('a@b.test', '09171234567', 'SMS', 's', 'h', 't', 'x')[2:], ('Website (delivery failed)', 'Failed'))
        self.assertEqual(A.notify_patient('', '', 'SMS', 's', 'h', 't', 'x')[2:], ('Website', 'Sent'))

    # ---- staff dashboard SMS button ----
    def _urgent(self, phone):
        sid, pw = make_user('clerk@example.test', role='Clinic Staff', name='Clerk'); c = A.app.test_client(); password_login(c, 'clerk@example.test', pw, patient=False)
        sql('DELETE FROM reminders WHERE patient_id IN (SELECT id FROM patients WHERE patient_id=?)', ('HK-SMS-1',)); sql('DELETE FROM patients WHERE patient_id=?', ('HK-SMS-1',))
        sql("INSERT INTO patients(patient_id,name,phone,email,channel,branch_id) VALUES(?,?,?,?,'SMS',1)", ('HK-SMS-1', 'Sms Pt', phone, ''))
        pid = row('SELECT id FROM patients WHERE patient_id=?', ('HK-SMS-1',))['id']
        return c, pid

    def test_urgent_sms_is_really_sent_and_logged(self):
        c, pid = self._urgent('09171234567')
        post(c, '/staff/login', f'/staff/urgent-contact/{pid}/sms', message='Please come back')
        self.assertEqual(self.sent, [('sms', '09171234567', 'Please come back')])
        self.assertEqual(row('SELECT channel,status FROM reminders WHERE patient_id=?', (pid,))['channel'], 'SMS + Website')

    def test_urgent_sms_failure_and_missing_phone(self):
        c, pid = self._urgent('09171234567'); self.sms_result = (False, 'rejected')
        post(c, '/staff/login', f'/staff/urgent-contact/{pid}/sms', message='hi')
        r = row('SELECT channel,status FROM reminders WHERE patient_id=?', (pid,)); self.assertEqual((r['channel'], r['status']), ('Website (SMS failed)', 'Failed'))
        sql('UPDATE patients SET phone=? WHERE id=?', ('', pid)); sql('DELETE FROM reminders WHERE patient_id=?', (pid,)); self.sent.clear()
        post(c, '/staff/login', f'/staff/urgent-contact/{pid}/sms', message='hi')
        self.assertEqual(self.sent, []); self.assertIsNone(row('SELECT id FROM reminders WHERE patient_id=?', (pid,)))


if __name__ == '__main__':
    unittest.main()
