"""A promo segment that expires between listing and fetching.

On 2026-09-25 AH started answering 404 for segment 811682, which it still
listed, and the unhandled error took every AH promotion down with it, run
after run.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bonusrank.db import connect
from bonusrank.ingest import ingest_ah
from bonusrank.models import RawOffer
from bonusrank.seed import load_seed


def _offer(group):
    return RawOffer(chain="ah", offer_id=group, group_id=group, title="Kwark",
                    category="Zuivel", promo_raw_text="2 voor 3.00",
                    promo_labels=[{"code": "DISCOUNT_X_FOR_Y", "defaultDescription": "2 voor 3.00",
                                   "count": 2, "price": 3.0}],
                    valid_from="2026-09-21", valid_to="2026-09-27")


class FakeAH:
    def __init__(self, status=404):
        self.status = status

    def fetch_promotions(self):
        return [_offer("811682"), _offer("100")]

    def fetch_segment(self, group):
        if group == "811682":
            url = f"https://api.ah.nl/mobile-services/bonuspage/v2/segment?segmentId={group}"
            raise httpx.HTTPStatusError("gone", request=httpx.Request("GET", url),
                                        response=httpx.Response(self.status))
        return {"products": [{"webshopId": 1, "title": "AH Magere kwark", "salesUnitSize": "500 g",
                              "priceBeforeBonus": 1.99, "currentPrice": 1.5}]}


@pytest.fixture()
def conn():
    c = connect(path=Path(":memory:"))
    load_seed(c)
    return c


def test_a_gone_segment_is_skipped_and_the_rest_still_counts(conn):
    stats = ingest_ah(conn, FakeAH())
    assert stats.segments_gone == 1
    assert stats.segments == 1
    assert conn.execute("SELECT count(*) FROM price_observations").fetchone()[0] == 1


def test_other_errors_still_fail_loudly(conn):
    with pytest.raises(httpx.HTTPStatusError):
        ingest_ah(conn, FakeAH(status=401))
