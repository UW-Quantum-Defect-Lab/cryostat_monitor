"""
This module provides all necessary methods to communicate with cryostat personnel via emails and Slack.
"""
import smtplib
import ssl
from typing import Sequence

import pandas as pd
import slack_sdk
from _socket import gaierror
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import Block

from monitor.constants import SLACK_WEBHOOK_URL, SLACK_OAUTH_TOKEN, SLACK_CHANNEL

_slack_web_client = slack_sdk.WebClient(token=SLACK_OAUTH_TOKEN)
""" The web client object defined by the `SLACK_OAUTH_TOKEN` constant. """
_slack_webhook_client = slack_sdk.WebhookClient(url=SLACK_WEBHOOK_URL)
""" The webhook client object defined by the `SLACK_WEBHOOK_URL` constant. """


def send_email(
        sender_id: str = '',
        sender_server: str = 'gmail.com',
        sender_password: str = '',
        recipients: str | Sequence[str] = '',
        subject: str = '',
        message: str = ''
) -> int:
    """
    Sends an e-mail to the recipients with the given message.

    The following code is a modified version of an example found on https://realpython.com/python-send-email/ and
    https://julien.danjou.info/sending-emails-in-python-tutorial-code-examples/ and for mail validation, the pyPI page/

    Parameters
    ----------
    sender_id : str
        The e-mail address of the sender.
    sender_server : str
        The server of the sender.
    sender_password : str
        The password of the sender.
    recipients : str | Sequence[str]
        The recipient(s) of the e-mail.
    subject : str
        The subject of the e-mail.
    message : str
        The message of the e-mail.

    Returns
    -------
    int
        The return code of the function.
        0: Success
        1: Failed to connect to the server. Bad connection settings?
        2: Failed to connect to the server. Wrong user/password?
        3: SMTP error occurred
    """

    if len(recipients) == 0:
        print('No recipients were given. Failed to send e-mail with message: ' + message)
        return 5

    # setting up server and sender parameters
    port = 587  # For starttls
    smtp_server = 'smtp.' + sender_server
    sender_email = sender_id + r'@' + sender_server

    # setting up email content
    context = ssl.create_default_context()
    # Adding the subject, and showing the sender (not necessary), and the other recipients (necessary)
    message = f"Subject: {subject}\nFrom: {sender_email}\nTo: {','.join(recipients)}\n\n{message}"

    try:
        with smtplib.SMTP(smtp_server, port) as server:
            server.ehlo()  # Can be omitted
            server.starttls(context=context)
            server.ehlo()  # Can be omitted
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipients, message)
            server.quit()
    except (gaierror, ConnectionRefusedError):
        # tell the script to report if your message was sent or which errors need to be fixed
        print('Failed to connect to the server. Bad connection settings?')
        return 1
    except smtplib.SMTPServerDisconnected:
        print('Failed to connect to the server. Wrong user/password?')
        return 2
    except smtplib.SMTPException as e:
        print('SMTP error occurred: ' + str(e))
        return 3
    else:
        print('Sent e-mail with message:\n' + message + '\n\nto: ' + ', '.join(recipients))
        return 0


def send_slack_message_via_webhook(message: str = None, blocks: list[Block] = None):
    """
    Sends a message to Slack via a webhook determined by thr `SLACK_WEBHOOK_URL` constant.

    Parameters
    ----------
    message : str
        The message to send.
    blocks : list[Block]
        The message blocks to send.
    """
    try:
        response = _slack_webhook_client.send(text=message, blocks=blocks)
        print(response.__dict__)
    except SlackApiError as e:
        print(f"Error posting message: {e}")


def send_slack_message_via_client(channel_name: str = SLACK_CHANNEL, message: str = None, blocks: list[Block] = None):
    """
    Sends a message to Slack via a Slack client.

    See more on: https://api.slack.com/messaging/sending
    Parameters
    ----------
    channel_name : str
        The name of the channel to send the message to.
    message : str
        The message to send.
    blocks : list[Block]
        The message blocks to send.
    """
    channel_conversion_id = _get_slack_channel_conversation_id(channel_name)
    try:
        response = _slack_web_client.chat_postMessage(channel=channel_conversion_id, text=message, blocks=blocks)
        print(response)
    except SlackApiError as e:
        print(f"Error posting message: {e}")


def _get_slack_channel_conversation_id(channel_name: str = SLACK_CHANNEL) -> str:
    """
    Converts channel name to channel ID.

    Returns
    -------
    str
        Channel ID.
        Empty string if channel ID was not found.
    """
    channel_conversation_id = None
    try:
        for result in _slack_web_client.conversations_list():
            if channel_conversation_id is not None:
                break
            for channel in result["channels"]:
                if channel["name"] == channel_name:
                    channel_conversation_id = channel["id"]
                    return channel_conversation_id
    except SlackApiError as e:
        print(f"Error: {e}")

    return ''


def dict_to_markdown_table(data: dict, column_names: tuple[str, str] = None):
    """
    Converts a dictionary into Markdown table text,
    with keys in the first column and values in the second column.

    Parameters
    ----------
    data : dict
        The dictionary to convert.
    column_names : tuple[str, str]
        The column names to use.

    Returns
    -------
    str
        The Markdown-table text.
    """
    df = pd.DataFrame(data.items(), columns=column_names)
    return f"```\n{df.to_markdown(index=False)}\n```"

