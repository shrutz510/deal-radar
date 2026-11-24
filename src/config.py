"""Settings you might want to tune. Everything else reads them from here."""
import os
from pathlib import Path

SRC = Path(__file__).resolve().parent
# data lives next to the repo, not inside src/; DEAL_RADAR_DB points elsewhere (e.g. one file per profile)
DB_PATH = Path(os.environ.get("DEAL_RADAR_DB") or SRC.parent / "deals.db")
STATIC_DIR = SRC / "static"

HOST = os.environ.get("DEAL_RADAR_HOST", "127.0.0.1")  # 0.0.0.0 inside a container
PORT = int(os.environ.get("DEAL_RADAR_PORT", "8787"))
REFRESH_EVERY_S = 30 * 60           # background refresh interval

USER_AGENT = "DealRadar/1.0 (personal deal tracker; RSS reader)"
REQUEST_GAP_S = 1.5                 # pause between requests to the same site
STORE_GAP_S = 5                     # pause between stores (Shopify rate-limits stores hit back to back)
RETRY_AFTER_MAX_S = 15              # longest we wait on a 429 before the single retry

FEED_DAYS = 14                      # how long deal-feed posts stay visible
PRODUCT_STALE_H = 26                # a store product not seen this long is gone (sold out or off sale)
