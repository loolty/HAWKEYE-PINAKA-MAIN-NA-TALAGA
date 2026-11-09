"""Text-message (SMS) sending for HawkEye.

Providers, chosen with SMS_PROVIDER in .env:

  demo       Free test mode. Nothing is sent: each message is written to logs/sms_demo.log and the app
             shows the reminder as "SMS (demo)". Use it for demos and while developing.
  traccar    Your own Android phone with the "Traccar SMS Gateway" app (on Google Play; free apart from your SIM
             load). Needs TRACCAR_SMS_TOKEN (the token shown in the app). To talk to the phone directly on your
             Wi-Fi instead of through Traccar's cloud, set TRACCAR_SMS_URL to the URL in the app and use the
             app's API key as the token.
  android    Your own Android phone as the gateway (free apart from your SIM load/promo), using the open-source
             "SMS Gateway for Android" app (capcom6). Needs ANDROID_SMS_USER and ANDROID_SMS_PASSWORD (shown in
             the app). ANDROID_SMS_URL is the app's API address: leave it empty for the app's Cloud mode, or set
             it to Local mode, e.g. http://192.168.1.50:8080 (the phone's Wi-Fi address).

  twilio     Works worldwide. Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and either
             TWILIO_FROM_NUMBER (e.g. +12025550123) or TWILIO_MESSAGING_SERVICE_SID.
  semaphore  Philippine provider (Philippine numbers only). Needs SEMAPHORE_API_KEY;
             SEMAPHORE_SENDER_NAME is optional (must be approved by Semaphore).

Leave SMS_PROVIDER empty to keep SMS switched off: send_sms() then returns (False, reason) and the
caller falls back to email / the patient website, exactly as before.

No third-party packages are needed (standard library only). send_sms() never raises.
"""
import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger('hawkeye.sms')

HTTP_TIMEOUT = 15          # seconds
DEMO_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'sms_demo.log')
TRACCAR_CLOUD_URL = 'https://www.traccar.org/sms/'
ANDROID_CLOUD_URL = 'https://api.sms-gate.app/3rdparty/v1'
SMS_MAX_CHARS = 320        # about two SMS segments; longer messages are shortened


def provider():
    """The configured provider ('twilio', 'semaphore', 'android', 'demo') or '' when SMS is off/unknown."""
    name = os.getenv('SMS_PROVIDER', '').strip().lower()
    if name in ('androidgw', 'android-gateway', 'phone'): name = 'android'
    return name if name in ('twilio', 'semaphore', 'android', 'traccar', 'demo') else ''


def is_configured():
    """True when SMS_PROVIDER is set and its credentials are present."""
    p = provider()
    if p == 'twilio':
        return bool(os.getenv('TWILIO_ACCOUNT_SID', '').strip() and os.getenv('TWILIO_AUTH_TOKEN', '').strip()
                    and (os.getenv('TWILIO_FROM_NUMBER', '').strip() or os.getenv('TWILIO_MESSAGING_SERVICE_SID', '').strip()))
    if p == 'semaphore':
        return bool(os.getenv('SEMAPHORE_API_KEY', '').strip())
    if p == 'traccar':
        return bool(os.getenv('TRACCAR_SMS_TOKEN', '').strip())
    if p == 'android':
        return bool(os.getenv('ANDROID_SMS_USER', '').strip() and os.getenv('ANDROID_SMS_PASSWORD', '').strip())
    return p == 'demo'


def channel_label():
    """What to call this channel on a reminder row: 'SMS (demo)' in demo mode, otherwise 'SMS'."""
    return 'SMS (demo)' if provider() == 'demo' else 'SMS'


def normalize_phone(raw):
    """Turn what a person typed into E.164 (+639171234567), or None if it is not a usable mobile number.

    Accepts 09171234567, 9171234567, 639171234567, +63 917 123 4567, 0063-917-123-4567, (0917) 123 4567 ...
    Numbers without a country code are assumed to belong to SMS_DEFAULT_COUNTRY_CODE (default 63, Philippines).
    """
    s = (raw or '').strip()
    if not s:
        return None
    if re.search(r'[^\d\s+\-().]', s):        # letters or other symbols: not a phone number
        return None
    plus = s.startswith('+')
    digits = re.sub(r'\D', '', s)
    cc = re.sub(r'\D', '', os.getenv('SMS_DEFAULT_COUNTRY_CODE', '63')) or '63'
    if plus:
        pass
    elif digits.startswith('00'):
        digits = digits[2:]
    elif digits.startswith('0'):
        digits = cc + digits[1:]
    elif digits.startswith(cc) and len(digits) > len(cc) + 7:
        pass
    else:
        digits = cc + digits
    # E.164: country code + subscriber number, at most 15 digits. Reject obviously short numbers.
    if not (9 <= len(digits) <= 15):
        return None
    if digits.startswith('63') and len(digits) != 12:      # Philippine mobile numbers: +63 9XX XXX XXXX
        return None
    return '+' + digits


def mask_phone(e164):
    """+639171234567 -> +63*******4567, for logs and flash messages."""
    return e164[:3] + '*' * max(0, len(e164) - 7) + e164[-4:] if e164 and len(e164) > 7 else '***'


def _post(url, fields, headers=None, as_json=False):
    """POST form fields (or a JSON body); returns (http_status, parsed_json_or_text). Raises URLError/OSError on network failure."""
    headers = dict(headers or {})
    if as_json:
        data = json.dumps(fields).encode('utf-8'); headers['Content-Type'] = 'application/json'
    else:
        data = urllib.parse.urlencode(fields).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode('utf-8', 'replace'); status = resp.status
    except urllib.error.HTTPError as exc:              # 4xx/5xx still carry a useful JSON body
        body = exc.read().decode('utf-8', 'replace'); status = exc.code
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


def _send_twilio(to, body):
    sid = os.getenv('TWILIO_ACCOUNT_SID', '').strip(); token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
    fields = {'To': to, 'Body': body}
    service = os.getenv('TWILIO_MESSAGING_SERVICE_SID', '').strip()
    if service: fields['MessagingServiceSid'] = service
    else: fields['From'] = os.getenv('TWILIO_FROM_NUMBER', '').strip()
    auth = base64.b64encode(f'{sid}:{token}'.encode()).decode()
    status, data = _post(f'https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json', fields,
                         {'Authorization': 'Basic ' + auth})
    if status in (200, 201) and isinstance(data, dict) and data.get('sid'):
        return True, 'SMS sent.'
    reason = data.get('message') if isinstance(data, dict) else str(data)[:200]
    log.error('Twilio rejected the SMS (HTTP %s): %s', status, reason)
    if status in (401, 403): return False, 'SMS login failed. Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.'
    return False, 'The SMS provider rejected the message' + (f': {reason}' if reason else '.')


def _send_semaphore(to, body):
    # Semaphore wants a Philippine number as 09XXXXXXXXX or 639XXXXXXXXX (no "+").
    number = to.lstrip('+')
    if not number.startswith('63'):
        return False, 'Semaphore can only send to Philippine numbers.'
    fields = {'apikey': os.getenv('SEMAPHORE_API_KEY', '').strip(), 'number': number, 'message': body}
    sender = os.getenv('SEMAPHORE_SENDER_NAME', '').strip()
    if sender: fields['sendername'] = sender
    status, data = _post('https://api.semaphore.co/api/v4/messages', fields)
    # A successful call returns a JSON list with one message object per recipient.
    if status in (200, 201) and isinstance(data, list) and data and isinstance(data[0], dict) \
            and str(data[0].get('status', '')).lower() not in ('failed', 'refunded'):
        return True, 'SMS sent.'
    reason = ''
    if isinstance(data, dict): reason = '; '.join(f'{k}: {v}' for k, v in data.items())[:200]
    elif isinstance(data, list) and data and isinstance(data[0], dict): reason = str(data[0].get('status', ''))
    else: reason = str(data)[:200]
    log.error('Semaphore rejected the SMS (HTTP %s): %s', status, reason)
    if status in (401, 403): return False, 'SMS login failed. Check SEMAPHORE_API_KEY.'
    return False, 'The SMS provider rejected the message' + (f': {reason}' if reason else '.')


def _send_android(to, body):
    """Send through the SMS Gateway for Android app. A 2xx answer means the phone/gateway ACCEPTED the message;
    the phone then sends it, so it must be switched on, have signal and (Cloud mode) internet."""
    base = (os.getenv('ANDROID_SMS_URL', '').strip() or ANDROID_CLOUD_URL).rstrip('/')
    if not base.lower().startswith(('http://', 'https://')):
        return False, 'ANDROID_SMS_URL must start with http:// or https://.'
    user = os.getenv('ANDROID_SMS_USER', '').strip(); pw = os.getenv('ANDROID_SMS_PASSWORD', '').strip()
    auth = base64.b64encode(f'{user}:{pw}'.encode()).decode()
    status, data = _post(base + '/message', {'textMessage': {'text': body}, 'phoneNumbers': [to]},
                         {'Authorization': 'Basic ' + auth}, as_json=True)
    if status in (200, 201, 202):
        return True, 'SMS handed to the phone gateway.'
    reason = (data.get('message') if isinstance(data, dict) else str(data)[:200]) or ''
    log.error('Android SMS gateway rejected the SMS (HTTP %s): %s', status, reason)
    if status in (401, 403): return False, 'Phone gateway login failed. Check ANDROID_SMS_USER and ANDROID_SMS_PASSWORD.'
    return False, 'The phone gateway rejected the message' + (f': {reason}' if reason else '.')


def _send_traccar(to, body):
    """Send through the Traccar SMS Gateway app (documented at traccar.org/http-sms-api). A 2xx answer means the
    gateway accepted the message; the phone then sends it, so it must be on and online."""
    url = os.getenv('TRACCAR_SMS_URL', '').strip() or TRACCAR_CLOUD_URL
    if not url.lower().startswith(('http://', 'https://')):
        return False, 'TRACCAR_SMS_URL must start with http:// or https://.'
    status, data = _post(url, {'to': to, 'message': body}, {'Authorization': os.getenv('TRACCAR_SMS_TOKEN', '').strip()}, as_json=True)
    if 200 <= status < 300:
        return True, 'SMS handed to the phone gateway.'
    reason = (data.get('message') if isinstance(data, dict) else str(data)[:200]) or ''
    log.error('Traccar SMS gateway rejected the SMS (HTTP %s): %s', status, reason)
    if status in (401, 403): return False, 'Phone gateway login failed. Check TRACCAR_SMS_TOKEN.'
    return False, 'The phone gateway rejected the message' + (f': {reason}' if reason else '.')


def _send_demo(to, body):
    """Free test mode: record the message instead of sending it."""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tto {mask_phone(to)}\t{body}"
    try:
        os.makedirs(os.path.dirname(DEMO_LOG), exist_ok=True)
        with open(DEMO_LOG, 'a', encoding='utf-8') as fh: fh.write(line + '\n')
    except OSError as exc:
        log.warning('Could not write the demo SMS log: %s', exc)
    log.info('DEMO SMS (not sent) %s', line)
    return True, 'Demo mode: the SMS was recorded in logs/sms_demo.log, not really sent.'


def send_sms(to_phone, message):
    """Send one text message. Returns (ok, detail). Never raises, so callers can show the result."""
    p = provider()
    if not p:
        return False, 'SMS is not switched on. Set SMS_PROVIDER (twilio or semaphore) and its credentials in .env.'
    if not is_configured():
        return False, f'SMS provider "{p}" is missing credentials in .env.'
    to = normalize_phone(to_phone)
    if not to:
        return False, 'The saved phone number is not a valid mobile number.'
    body = ' '.join((message or '').split())
    if not body:
        return False, 'Nothing to send.'
    if len(body) > SMS_MAX_CHARS:
        body = body[:SMS_MAX_CHARS - 3].rstrip() + '...'
    try:
        ok, detail = {'twilio': _send_twilio, 'semaphore': _send_semaphore, 'android': _send_android, 'traccar': _send_traccar, 'demo': _send_demo}[p](to, body)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        log.error('SMS network error (%s): %s', p, exc)
        if p in ('android', 'traccar'): return False, 'Could not reach the phone gateway. Is the app running, is the phone online, and is ANDROID_SMS_URL right?'
        return False, 'Could not reach the SMS provider. Check the internet connection.'
    except Exception:                                      # never let an SMS problem break a request or the scheduler
        log.exception('Unexpected SMS error (%s)', p)
        return False, 'Unexpected SMS error. See the server log.'
    if ok and p != 'demo': log.info('SMS sent through %s to %s', p, mask_phone(to))
    return ok, detail
