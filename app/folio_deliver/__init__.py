"""Folio Show (formerly Folio Deliver): presentations."""
import os

VERSION = "0.9.0"
APP_NAME = "Folio Show"
APP_ID = "org.folio.Show"
SHARE = os.environ.get("FOLIO_SHOW_SHARE") or os.environ.get("FOLIO_DELIVER_SHARE") or "/usr/share/folio-show"
