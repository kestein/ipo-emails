import argparse
import asyncio
import sys

from aiohttp import BasicAuth, ClientSession
import yarl

async def main(base_url, api_key, from_addr, to_addrs):
    base_url = yarl.URL(base_url) / "messages"
    payload = {
        "from": from_addr,
        "to": to_addrs,
        "subject": "TEST",
        "text": "This is a test email\n\n //Tester"
    }
    async with ClientSession() as session:
        async with session.post(base_url, auth=BasicAuth("api", api_key), data=payload) as resp:
            resp.raise_for_status()
            print(await resp.json())


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
