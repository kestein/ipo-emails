import argparse
import asyncio
import sys

import httpx
import yarl

NYSE_LINK = "https://www.nyse.com/api/ipo-center/calendar"

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
    def __init__(self, name, symbol, amount_filed, shares_filed, price_range):
        self.name = name
        self.symbol = symbol
        self.amount_filed = int(amount_filed) if int(amount_filed) == amount_filed else amount_filed
        self.shares_filed = int(shares_filed) if int(shares_filed) == shares_filed else shares_filed
        self.price_range = price_range

    def __str__(self):
        return "\n".join(
            [
                f"Company: {self.name} ({self.symbol})",
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
    return [
        NYSE(c["issuer_nm"], c["symbol"], c["current_filed_proceeds_with_overallotment_usd_amt"], c["current_shares_filed"], c["current_file_price_range_usd"])
        for c in payload["calendarList"]
    ]


async def main(base_url, api_key, from_addr, to_addrs):
    base_url = yarl.URL(base_url) / "messages"
    payload = {
        "from": from_addr,
        "to": to_addrs,
        "subject": "NYSE IPOs"
    }
    async with httpx.AsyncClient() as session:
        payload["text"] = "\n".join([str(c) for c in await get_nyse(session)])
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
