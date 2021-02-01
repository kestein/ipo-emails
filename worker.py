import argparse
import asyncio
import datetime
import sys

import httpx
import yarl

NYSE_LINK = "https://www.nyse.com/api/ipo-center/calendar"
NASDAQ_LINK = yarl.URL("https://api.nasdaq.com/api/ipo/calendar")
# Nasdaq requests require a user agent that looks like a browser
CHROME_UA = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.104 Safari/537.36"


def make_company_line(name, symbol) -> str:
    return f"Company: {name} ({symbol})" if symbol else f"Company: {name}"

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
        chares_filed = payload["current_shares_filed"]
        self.shares_filed = int(shares_filed) if int(shares_filed) == shares_filed else shares_filed
        self.price_range = payload["current_file_price_range_usd"]

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
    "sharesOffered": "8,600,977",
    "expectedPriceDate": "02/03/2021",
    "dollarValueOfSharesOffered": "$494,556,150.00"
}
"""
class Nasdaq:
     def __init__(self, payload):
        self.name = payload["companyName"]
        self.symbol = payload["proposedTickerSymbol"]
        amount_filed = "sharesOffered"
        self.amount_filed = int(amount_filed) if int(amount_filed) == amount_filed else amount_filed
        self.price_range = payload["proposedSharePrice"]

    def __str__(self):
        return "\n".join(
            [
                make_company_line(self.name, self.symbol),
                f"Offering: {self.amount_filed}",
                f"Price: {self.price_range}"
            ]
        )


async def get_nasdaq(session):
    # TODO: Resolve what happens when a week spans 2 months
    req = NASDAQ_LINK.with_query(("date", datetime.utcnow().strftime("%Y-%m"))
    resp = await session.get(str(req)), headers={"user-agent": CHROME_UA})
    if resp.status_code != 200:
        print(f"non 200  status {resp.status_code}: {resp.json()}")
        return []
    payload = resp.json()
    return [Nasdaq(c) for c in payload["data"]["upcoming"]]


async def main(base_url, api_key, from_addr, to_addrs):
    base_url = yarl.URL(base_url) / "messages"
    payload = {
        "from": from_addr,
        "to": to_addrs,
        "subject": "NYSE IPOs"
    }
    async with httpx.AsyncClient() as session:
        nyse, nasdaq = await asyncio.gather(get_nasdaq(session), get_nyse(session))
        payload["text"] = "\n\n".join([str(c) for c in chain(nyse, nasdaq)])
        resp = await session.post(str(base_url), auth=("api", api_key), data=payload)
        resp.raise_for_status()
        print(resp.json())


def parse_cli_args():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--to-addrs', metavar='N', type=str, nargs='+', help='Emails to send to')
    parser.add_argument('--from-addr', type=str, help='The from email address')
    parser.add_argument('--base-api-url', type=str, help='Base email URL from mailgun')
    parser.add_argument('--api-key', type=str, help='Mailgun API key')

    return parser.parse_args()



if __name__ == "__main__":
    args = parse_cli_args()

    asyncio.run(main(args.base_api_url, args.api_key, args.from_addr, args.to_addrs))
