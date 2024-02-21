"""
This module defines various constants used throughout
the definition of the cryostat monitor methods and classes.
"""

import datetime
import os
from pathlib import Path

import yaml


def _get_dropbox_path():
    """Retrieves the Dropbox folder path, handling potential errors."""

    path = os.environ.get("DROPBOX_PATH")
    if path is not None:
        return Path(path)

    # Environment variable not set, try common default locations:
    home = Path.home()
    potential_paths = [
        home / "Dropbox",
        home / "Documents/Dropbox",
        Path("/Users/Shared/Dropbox"),  # macOS
        Path("C:/Users/Public/Dropbox"),  # Windows
    ]

    for path in potential_paths:
        if path.exists():
            return path

    # If none of the above paths exist, raise an error:
    raise FileNotFoundError("Dropbox folder not found in expected locations.")


DATA_FILENAME_FORMAT = '%Y/%Y-%m-%d_MagnetLogger.csv'
""" Cryostat monitor filename format (includes sub-folders). """
ALERT_FILENAME_FORMAT = '%Y/%Y-%m-%d_Alerts.csv'
""" Cryostat monitor alter message logfile name format (includes sub-folders). """
FILE_TIMESTAMP_FORMAT = '%H:%M:%S'
""" Cryostat monitor timestamp format. """
EMAIL_TIMESTAMP_FORMAT = '%H:%M'
""" Alert message timestamp format. """

STATUS_CHANGE_DISCARD_TIME = 24  # hours
""" Time between resending alerts on persistent problems. """
NITROGEN_REFILLING_FOR_TOO_LONG = 1  # hours
""" Time it takes to conclude that the nitrogen dewar is empty. """
DAILY_REPORT_TIMES = [datetime.time(hour=7, minute=30), datetime.time(hour=15), datetime.time(hour=21, minute=30)]
""" Times of day when daily reports are sent. """

_DROPBOX_PATH = _get_dropbox_path()
""" The local dropbox path. """
# DATA_STORAGE_FOLDER = _DROPBOX_PATH.joinpath('35share/magnetlog/test_data')
DATA_STORAGE_FOLDER = _DROPBOX_PATH.joinpath('35share/magnetlog/data')
""" The parent folder path to store data. """

SUPPORTING_FILES_FOLDER = _DROPBOX_PATH.joinpath('35share/magnetlog/qdl_cryostat_monitor/monitor/supporting_files')

# EMAIL_INFO_FILE_PATH = SUPPORTING_FILES_FOLDER / 'email_info_test.yaml'
EMAIL_INFO_FILE_PATH = SUPPORTING_FILES_FOLDER / 'email_info.yaml'
""" The path to the email information file. """


SLACK_COMMUNICATION_SETTINGS_FILE_PATH = SUPPORTING_FILES_FOLDER / 'slack_communication.yaml'

with open(SLACK_COMMUNICATION_SETTINGS_FILE_PATH, 'r') as file:
    SLACK_COMMUNICATION_SETTINGS = yaml.safe_load(file)

# SLACK_WEBHOOK_URL = SLACK_COMMUNICATION_SETTINGS['slack_webhook_url_test']
SLACK_WEBHOOK_URL = SLACK_COMMUNICATION_SETTINGS['slack_webhook_url_production']
""" The slack webhook link to use. """
SLACK_OAUTH_TOKEN = SLACK_COMMUNICATION_SETTINGS['slack_oauth_token']
""" The slack oauth token to use. """
SLACK_CHANNEL = SLACK_COMMUNICATION_SETTINGS['slack_channel']
""" The slack channel to send messages to (if the oath token is used instead of the webhook). """
