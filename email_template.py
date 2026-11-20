"""
email_template.py  -  drop this file next to app.py

Gives you:
  clinic_email(...)      -> styled HTML like the DentaCore "Booking Confirmed" email
  sender_header()        -> "HawkEye Optical Clinic <your@gmail.com>" so the clinic name shows
"""
import os
from email.utils import formataddr
from markupsafe import escape as esc

CLINIC_NAME = os.getenv('CLINIC_NAME', 'HawkEye Optical Clinic')
CLINIC_TAGLINE = os.getenv('CLINIC_ADDRESS', '')          # shown under the title if set

# Colours (change to match your brand)
# HawkEye brand colours (taken from the site's tokens.css / logo)
RED, RED_DARK, RED_TINT, RED_LINE = '#ed2b20', '#c8231a', '#fff3f1', '#f3b9b4'
PAGE_BG, CARD, WHITE = '#f4f5f7', '#ffffff', '#ffffff'
TEXT, MUTED, LINE = '#12151a', '#565d6a', '#dfe2e7'


def sender_header():
    """Display name + address. Recipients see 'HawkEye Optical Clinic', not your name."""
    addr = os.getenv('GMAIL_ADDRESS', os.getenv('MAIL_USERNAME', '')).strip()
    return formataddr((CLINIC_NAME, addr))


def clinic_email(title, greeting_name, intro, rows=None, footer_note='', closing=True, code=None, button=None):
    """
    title          heading, e.g. 'Appointment Reminder'
    greeting_name  patient name
    intro          sentence(s) under the greeting (plain text; already escaped here)
    rows           list of (label, value) shown in the details box
    footer_note    extra paragraph under the box
    code           optional big verification code, e.g. '482913'
    button         optional (label, url) tuple shown as a red button
    """
    code_html = (f'<div style="text-align:center;margin:20px 0;"><span style="display:inline-block;background:{RED_TINT};'
                 f'border:1px solid {RED_LINE};border-radius:10px;padding:14px 26px;font-size:30px;font-weight:bold;'
                 f'letter-spacing:8px;color:{RED_DARK};">{esc(code)}</span></div>') if code else ''
    button_html = (f'<div style="text-align:center;margin:22px 0;"><a href="{esc(button[1])}" style="display:inline-block;'
                   f'background:{RED_DARK};color:{WHITE};text-decoration:none;font-weight:bold;font-size:15px;'
                   f'padding:12px 26px;border-radius:8px;">{esc(button[0])}</a></div>') if button else ''
    rows_html = ''.join(
        f'<tr><td style="padding:9px 0;color:{MUTED};font-size:14px;">{esc(k)}</td>'
        f'<td style="padding:9px 0;color:{TEXT};font-size:14px;font-weight:bold;text-align:right;">{esc(v)}</td></tr>'
        for k, v in (rows or [])
    )
    box = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'style="background:{RED_TINT};border:1px solid {RED_LINE};border-radius:10px;margin:18px 0;">'
           f'<tr><td style="padding:10px 18px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
           f'{rows_html}</table></td></tr></table>') if rows_html else ''
    note = f'<p style="color:{TEXT};font-size:14px;line-height:1.6;">{esc(footer_note)}</p>' if footer_note else ''
    regards = (f'<p style="color:{RED_DARK};font-style:italic;font-size:14px;margin-top:22px;">'
               f'Warm regards,<br>{esc(CLINIC_NAME)} Team</p>') if closing else ''
    sub = f'<div style="font-size:11px;letter-spacing:2px;color:#ffe3e0;margin-top:4px;">{esc(CLINIC_TAGLINE.upper())}</div>' if CLINIC_TAGLINE else ''

    return f'''<!DOCTYPE html>
<html><body style="margin:0;padding:24px 12px;background:{PAGE_BG};font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
  <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">
    <tr><td align="center" style="background:{RED};border-radius:8px 8px 0 0;padding:22px 16px;">
        <div style="font-size:24px;font-weight:bold;color:{WHITE};">{esc(CLINIC_NAME)}</div>{sub}
    </td></tr>
    <tr><td style="background:{CARD};padding:26px 24px;border-radius:0 0 8px 8px;border:1px solid {LINE};border-top:0;">
        <h2 style="margin:0 0 16px;color:{RED_DARK};font-size:19px;">{esc(title)}</h2>
        <p style="color:{TEXT};font-size:15px;">Dear <b>{esc(greeting_name)}</b>,</p>
        <p style="color:{TEXT};font-size:15px;line-height:1.6;">{esc(intro)}</p>
        {code_html}{button_html}{box}{note}{regards}
    </td></tr>
    <tr><td align="center" style="padding:16px;color:{MUTED};font-size:11px;line-height:1.6;">
        This is an automatic message from {esc(CLINIC_NAME)}. Please do not reply to this email.<br>
        &copy; {esc(CLINIC_NAME)}. All rights reserved.
    </td></tr>
  </table>
</td></tr></table>
</body></html>'''
