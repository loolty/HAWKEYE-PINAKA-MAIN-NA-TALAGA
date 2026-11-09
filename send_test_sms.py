"""Send one test SMS using the settings in .env and print exactly what happened.

    python send_test_sms.py 09171234567
    python send_test_sms.py 09171234567 "My own message"

Run it from the project folder, with the virtual environment active. It does not touch the database.
"""
import os, sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
import sms

if len(sys.argv) < 2:
    sys.exit('Usage: python send_test_sms.py <phone number> [message]')
phone = sys.argv[1]; text = sys.argv[2] if len(sys.argv) > 2 else 'HawkEye test message. If you can read this, SMS works.'

print('SMS_PROVIDER      :', os.getenv('SMS_PROVIDER', '').strip() or '(empty - SMS is OFF)')
print('Provider recognised:', sms.provider() or 'NO (use traccar, android, semaphore, twilio or demo)')
print('Credentials present:', 'yes' if sms.is_configured() else 'NO - a required setting is missing in .env')
print('Number as sent     :', sms.normalize_phone(phone) or 'INVALID - not a usable mobile number')
ok, detail = sms.send_sms(phone, text)
print('\nResult:', 'OK' if ok else 'FAILED', '-', detail)
if ok and sms.provider() in ('traccar', 'android'):
    print('The gateway accepted it. If nothing arrives: open the app on the phone, check it is online, has signal/load, and has SMS permission.')
if ok and sms.provider() == 'demo':
    print('Demo mode sends nothing. Look in logs/sms_demo.log.')
