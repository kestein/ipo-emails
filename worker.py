import argparse
import asyncio
from datetime import datetime, timedelta
from itertools import chain
from functools import partial
import os
import sys
from typing import Optional

import aioredis
import httpx
import pytz
import yarl

NYSE_LINK = "https://www.nyse.com/api/ipo-center/calendar"
NASDAQ_LINK = yarl.URL("https://api.nasdaq.com/api/ipo/calendar")
LAST_SENT_KEY = "email_last_sent"
# Nasdaq requests require a user agent that looks like a browser
CHROME_UA = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.104 Safari/537.36"
PACIFC_TIMEZONE = pytz.timezone("US/Pacific")
SATURDAY = 6
SUNDAY = 0


def make_company_line(name, symbol) -> str:
    return f"Company: {name} ({symbol})" if symbol else f"Company: {name}"


def parse_date(date_str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError as e:
        print(str(e))
        return None


def filter_company(company, dow=None):
    return company.expected_date is not None and company.expected_date.isoweekday() == dow

"""
    {
        "amended_file_dt": 1611792000000,
        "amended_filing_vs_offer_px_desc": "N/A",
        "bookrunners_parentCode": "MS, GS, JPM, BAML",
        "current_file_price_range_usd": "20.00 - 23.00",
        "current_filed_proceeds_with_overallotment_usd_amt": 370875000,
        "current_shares_filed": 15000000,
        "custom_group_exchange_nm": "NASDAQ",
        "custom_group_industry_nm": "Healthcare",
        "deal_status_desc": "Expected",
        "deal_status_flg": "E",
        "expected_dt_report": "02/03/2021",
        "init_file_dt": 1610409600000,
        "issuer_nm": "Sana Biotechnology, Inc.",
        "offer_greenshoe_inc_proceeds_usd_amt": 0,
        "offer_px_usd": 0,
        "offer_size_inc_shoe_qty": 0,
        "price_dt": null,
        "symbol": "SANA",
        "withdrawn_postponed_dt": null,
        "withdrawn_postponed_txt": null
    }
"""
class NYSE:
    def __init__(self, payload):
        self.name = payload["issuer_nm"]
        self.symbol = payload["symbol"]
        amount_filed = payload["current_filed_proceeds_with_overallotment_usd_amt"]
        self.amount_filed = int(amount_filed) if int(amount_filed) == amount_filed else amount_filed
        shares_filed = payload["current_shares_filed"]
        self.shares_filed = int(shares_filed) if int(shares_filed) == shares_filed else shares_filed
        self.price_range = payload["current_file_price_range_usd"]
        self.expected_date = parse_date(payload["expected_dt_report"])

    def __str__(self):
        return "\n".join(
            [
                make_company_line(self.name, self.symbol),
                f"Offering: {self.shares_filed} / {self.amount_filed}",
                f"Price: {self.price_range}"
            ]
        )


async def get_nyse(session):
    resp = await session.get(NYSE_LINK)
    if resp.status_code != 200:
        print(f"non 200  status {resp.status_code}: {resp.json()}")
        return []
    payload = resp.json()
    return [NYSE(c) for c in payload["calendarList"]]


"""
{
    "dealID": "373578-95383",
    "proposedTickerSymbol": "ONTF", // nullable
    "companyName": "ON24 INC",
    "proposedExchange": "NYSE",
    "proposedSharePrice": "45.00-50.00",
    "sharesOffered": "8,600,977", // nullable
    "expectedPriceDate": "02/03/2021",
    "dollarValueOfSharesOffered": "$494,556,150.00"
}
"""
class Nasdaq:
    def __init__(self, payload):
        print(payload)
        self.name = payload["companyName"]
        self.symbol = payload["proposedTickerSymbol"]
        amount_filed = payload["sharesOffered"].replace(",", "")
        if amount_filed:
            self.amount_filed = int(amount_filed) if int(amount_filed) == amount_filed else amount_filed
        else:
            self.amount_filed = "Unspecified"
        self.price_range = payload["proposedSharePrice"]
        self.expected_date = parse_date(payload["expectedPriceDate"])

    def __str__(self):
        return "\n".join(
            [
                make_company_line(self.name, self.symbol),
                f"Offering: {self.amount_filed}",
                f"Price: {self.price_range}"
            ]
        )


def utcnow():
    return datetime.utcnow().replace(tzinfo=pytz.UTC)


def pacnow():
    return utcnow().astimezone(PACIFC_TIMEZONE)


async def is_sendable_time(redis) -> bool:
    last_sent = await get_last_sent(redis)
    if not last_sent:
        return True

    last_send_time = datetime.fromisoformat(last_sent).replace(tzinfo=pytz.UTC)
    current_time_pac = pacnow()
    if current_time_pac.isoweekday() == SATURDAY:
        return False

    # (b/w 8 and 10 when last send was a different day) or (no email for over a day)
    return (8 <= current_time_pac.hour <= 10 and last_send_time.day != current_time_pac.day) or current_time_pac - last_send_time >= timedelta(days=1)


async def get_nasdaq(session):
    # TODO: Resolve what happens when a week spans 2 months
    month_qp = datetime.utcnow().strftime("%Y-%m")
    req = NASDAQ_LINK.with_query({"date": month_qp})
    resp = await session.get(str(req), headers={"user-agent": CHROME_UA})
    if resp.status_code != 200:
        print(f"non 200  status {resp.status_code}: {resp.json()}")
        return []
    payload = resp.json()
    return [Nasdaq(c) for c in payload["data"]["upcoming"]["upcomingTable"]["rows"]]


async def get_last_sent(redis) -> Optional[datetime]:
    if not redis:
        return None
    return await redis.get(LAST_SENT_KEY, encoding="utf-8")


async def set_last_sent(redis):
    if not redis:
        return
    await redis.set(LAST_SENT_KEY, datetime.utcnow().isoformat())


async def main(base_url, api_key, from_addr, to_addrs, ignore_redis):
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url or ignore_redis:
        print(f"No redis server URL set / ignore redis is {ignore_redis}")
        redis = None
    else:
        redis = await aioredis.create_redis_pool(redis_url)

    if not await is_sendable_time(redis):
        print("Not a sendable time")
        return

    base_url = yarl.URL(base_url) / "messages"
    dow = pacnow().isoweekday()
    daystr = "This week" if dow == SUNDAY else "Today"
    payload = {
        "from": from_addr,
        "to": to_addrs,
        "subject": f"{daystr}'s IPOs"
    }
    async with httpx.AsyncClient(timeout=5.0) as session:
        nyse = await get_nyse(session)
        nasdaq = await get_nasdaq(session) if os.environ.get("ENABLE_NASDAQ_EMAIL") else []
        filtered_companies = chain(nyse, nasdaq)
        if dow != SUNDAY:
            filtered_companies = filter(partial(filter_company, dow=dow), filtered_companies)
        payload["text"] = "\n\n".join([str(c) for c in filtered_companies])
        resp = await session.post(str(base_url), auth=("api", api_key), data=payload)
        resp.raise_for_status()
        print(resp.json())
    await set_last_sent(redis)


def parse_cli_args():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--to-addrs', metavar='N', type=str, nargs='+', help='Emails to send to')
    parser.add_argument('--from-addr', type=str, help='The from email address')
    parser.add_argument('--base-api-url', type=str, help='Base email URL from mailgun')
    parser.add_argument('--api-key', type=str, help='Mailgun API key')
    parser.add_argument('--ignore-redis', action="store_true", help='Do not check redis for last sent (debug')

    return parser.parse_args()

if __name__ == "__main__":
    args = parse_cli_args()

    asyncio.run(main(args.base_api_url, args.api_key, args.from_addr, args.to_addrs, args.ignore_redis))
