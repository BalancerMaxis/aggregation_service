import os

from dotenv import load_dotenv
from web3 import Web3

from aggregation.pipeline_process import process_payloads
from aggregation.tx_builder import generate_payload


def main() -> None:
    load_dotenv()
    process_payloads(week="W4269")
    web3 = Web3(Web3.HTTPProvider(os.environ["ETHNODEURL"]))
    generate_payload(web3=web3, week="W4269")


if __name__ == "__main__":
    main()
