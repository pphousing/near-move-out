from flask import Flask, render_template, request
import pandas as pd
import os
from google.oauth2.credentials import Credentials
import gspread
from google.auth.transport.requests import Request
import googlemaps
from dotenv import load_dotenv
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import json
from flask import session
from io import StringIO
import re
import requests
from math import radians, sin, cos, sqrt, atan2
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import os

# Load environment variables from .env file
load_dotenv()
print("GOOGLE_MAPS_API_KEY:", os.environ.get("GOOGLE_MAPS_API_KEY"))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')  # <-- Add this line


SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive',
         'https://www.googleapis.com/auth/gmail.send']
gmaps = googlemaps.Client(key=os.environ.get("GOOGLE_MAPS_API_KEY"))

def authenticate_google():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds
def get_gmail_service():
    creds = authenticate_google()
    return build('gmail', 'v1', credentials=creds)

def create_message(to, subject, body_text):
    message = MIMEText(body_text, 'html')
    message['to'] = to
    message['subject'] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes())
    return {'raw': raw.decode()}

def send_email(service, to, subject, body):
    message = create_message(to, subject, body)
    
    send_args = {
        'userId': 'me',
        'body': message
    }

    sent = service.users().messages().send(**send_args).execute()
    return sent

def send_text(phone_num, message, first_name):
    url = "https://api.openphone.com/v1/messages"
    headers={
        "Authorization": os.environ.get("AUTHORIZATION"),
        "Content-Type":"application/json"
    }
    first_name = first_name.title()
    if first_name =='Charlie':
        payload = {
            "content": message,
            "from": "PNvnUZwoP3",
            "to":[phone_num],
            "userId":"USMZbFI72a"
        }
    elif first_name == 'Mahmoud':
        payload = {
        "content": message,
        "from": "PNaOHVFQas",
        "to":[phone_num],
        "userId":"UStOusLc0x"
    }
    elif first_name == 'Ahmed':
        payload = {
        "content": message,
        "from":  'PNVYQxBEmb',
        "to":[phone_num],
        "userId":'USNNA3aaH3'
    }
    elif first_name == 'Mohamed':
        payload = {
        "content": message,
        "from":  'PNecGwld3E',
        "to":[phone_num],
        "userId":'USkdRcH9dR'
    }
    elif first_name == 'Sara':
        payload = {
        "content": message,
        "from":  'PN9mu12wlD',
        "to":[phone_num],
        "userId":'USPE5q7t2R'
    }
    response = requests.post(url,headers=headers, json = payload)
    return response

def extract_10_digit_number(phone_str):
    # Find all digits
    digits = re.findall(r'\d', phone_str)
    # Join and extract the last 10 digits (in case it includes country code)
    return '+1' + ''.join(digits)[-10:]


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", filters=json.dumps({}), phone_status_html=None, email_status_html=None)




@app.route('/send_messages', methods=['POST'])
def send_messages():
    filters = json.loads(request.form.get('filters', '{}'))

    ll_name = str(request.form.get('ll_name', ''))
    ll_email = str(request.form.get('ll_email', ''))
    insured_name = str(request.form.get('insured_name', ''))
    address = str(request.form.get('address', ''))
    lease_end_date = str(request.form.get('lease_end_date', ''))
    date_requested = str(request.form.get('date_requested', ''))
    claim_id = str(request.form.get('claim_id', ''))
    num_days = int(request.form.get('num_days', 0))
    rsd_amount = int(request.form.get('rsd_amount', 0))

    gc_phone_template = (
        f"Hi {insured_name}! I hope you’re doing well. As a reminder, the lease for "
        f"{address} will be completed in {num_days} days. {ll_name} will be sending "
        f"you check out instructions shortly, thank you!"
    )

    ll_email_template = (
        "Dear {ll_name},<br><br>"
        "I hope you're doing well. As a reminder, the lease for {address} will be completed "
        "in {num_days} days. After you complete your post checkout inspection, please refund "
        "the security deposit amount of ${rsd_amount} directly to us via Zelle at "
        "info@paradisepointhousing.com under Paradise Point Housing LLC.<br><br>"
        "Thank you for the opportunity to do business with you!<br><br>"
        "Sincerely,<br>"
        "Paradise Point Housing"
    )

    rsd_slack_template = """<!channel>
{address}
Landlord: {ll_name}
Client: {insured_name}
Lease end date: {lease_end_date}
RSD Amount: {rsd_amount}
Date Requested: {date_requested}
Claim ID #: {claim_id}
"""

    nmo_slack_template = """<!channel>
Claim ID #: {claim_id} Emailed/Texted GC
"""

    rsd_results = []
    nmo_results = []

    submitted_data = {
        "Landlord Name": ll_name,
        "Landlord Email": ll_email,
        "Insured Name": insured_name,
        "Address": address,
        "Lease End Date": lease_end_date,
        "Date Requested": date_requested,
        "Claim ID": claim_id,
        "Days Until Lease End": num_days,
        "RSD Amount": rsd_amount,
    }

    # 1) Slack - RSD channel
    try:
        SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
        RSD_CHANNEL_ID = "C096VLL6LBS"
        client = WebClient(token=SLACK_BOT_TOKEN)

        rsd_slack_text = rsd_slack_template.format(
            address=address,
            ll_name=ll_name,
            insured_name=insured_name,
            lease_end_date=lease_end_date,
            rsd_amount=rsd_amount,
            date_requested=date_requested,
            claim_id=claim_id
        )

        rsd_slack_response = client.chat_postMessage(
            channel=RSD_CHANNEL_ID,
            text=rsd_slack_text
        )

        rsd_results.append({
            "channel": "refundable-security-deposit-return",
            "recipient": RSD_CHANNEL_ID,
            "status": f"Sent ({rsd_slack_response['ts']})"
        })

    except SlackApiError as e:
        rsd_results.append({
            "channel": "refundable-security-deposit-return",
            "recipient": "C096VLL6LBS",
            "status": f"ERROR: {e.response['error']}"
        })
    except Exception as e:
        rsd_results.append({
            "channel": "refundable-security-deposit-return",
            "recipient": "C096VLL6LBS",
            "status": f"ERROR: {str(e)}"
        })

    # 2) Slack - Near Move Out channel
    try:
        SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
        NMO_CHANNEL_ID = "C0A84R920G5"
        client = WebClient(token=SLACK_BOT_TOKEN)

        nmo_slack_text = nmo_slack_template.format(
            claim_id=claim_id
        )

        nmo_slack_response = client.chat_postMessage(
            channel=NMO_CHANNEL_ID,
            text=nmo_slack_text
        )

        nmo_results.append({
            "channel": "near-move-out",
            "recipient": NMO_CHANNEL_ID,
            "status": f"Sent ({nmo_slack_response['ts']})"
        })

    except SlackApiError as e:
        nmo_results.append({
            "channel": "near-move-out",
            "recipient": "C0A84R920G5",
            "status": f"ERROR: {e.response['error']}"
        })
    except Exception as e:
        nmo_results.append({
            "channel": "near-move-out",
            "recipient": "C0A84R920G5",
            "status": f"ERROR: {str(e)}"
        })

    # 3) Gmail
    try:
        gmail_service = get_gmail_service()
        near_moveout_email = send_email(
            gmail_service,
            to=ll_email,
            subject=f"Refundable Security Deposit + Checkout Instructions: {address}/{insured_name} Family",
            body=ll_email_template.format(
                ll_name=ll_name,
                address=address,
                num_days=num_days,
                rsd_amount=rsd_amount
            )
        )

        rsd_results.append({
            "channel": "Gmail",
            "recipient": f"{ll_name} ({ll_email})",
            "status": "Sent"
        })
    except Exception as e:
        rsd_results.append({
            "channel": "Gmail",
            "recipient": f"{ll_name} ({ll_email})",
            "status": f"ERROR: {str(e)}"
        })

    rsd_results_df = pd.DataFrame(rsd_results)
    rsd_results_html = rsd_results_df.to_html(
        classes="table table-bordered table-striped",
        index=False,
        escape=False
    ) if not rsd_results_df.empty else None

    nmo_results_df = pd.DataFrame(nmo_results)
    nmo_results_html = nmo_results_df.to_html(
        classes="table table-bordered table-striped",
        index=False,
        escape=False
    ) if not nmo_results_df.empty else None

    submitted_data_df = pd.DataFrame(
        list(submitted_data.items()),
        columns=["Field", "Value"]
    )
    submitted_data_html = submitted_data_df.to_html(
        classes="table table-bordered table-striped",
        index=False,
        escape=False
    )

    gc_phone_template_text = f"Copy and paste this for the groupchat:\n\n{gc_phone_template}"

    return render_template(
        "index.html",
        filters=json.dumps(filters),
        submitted_data=submitted_data,
        submitted_data_html=submitted_data_html,
        rsd_results_html=rsd_results_html,
        nmo_results_html=nmo_results_html,
        gc_phone_template=gc_phone_template,
        gc_phone_template_text=gc_phone_template_text
    )
    

   





if __name__ == '__main__':
    # app.run(debug=True)
    # Use the PORT environment variable or default to 5000 for local testing
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)