"""Folio Show (formerly Folio Deliver): presentations."""
import os

VERSION = "0.13.0"
APP_NAME = "Folio Show"
APP_ID = "org.folio.Show"
SHARE = (os.environ.get("FOLIO_SHOW_SHARE") or os.environ.get("FOLIO_DELIVER_SHARE")
         or (os.path.join(os.environ["FOLIO_ROOT"], "share", "folio-show") if os.environ.get("FOLIO_ROOT") else None)
         or "/usr/share/folio-show")
