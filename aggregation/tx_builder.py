import copy
import csv
import json
import os
from datetime import date
from typing import Dict
from typing import List
from typing import Union

import requests
from bal_addresses import AddrBook
from web3 import Web3


address_book = AddrBook("mainnet")
safe = address_book.multisigs.fees
today = str(date.today())

SNAPSHOT_URL = "https://hub.snapshot.org/graphql?"
HH_API_URL = "https://api.hiddenhand.finance/proposal"
GAUGE_MAPPING_URL = "https://raw.githubusercontent.com/aurafinance/aura-contracts/main/tasks/snapshot/gauge_choices.json"

# queries for choices and proposals info
QUERY_PROPOSAL_INFO = """
query ($proposal_id: String) {
  proposal(id: $proposal_id) {
    choices
  }
}
"""

with open("aggregation/templates/bribe_balancer.json") as f:
    PAYLOAD = json.load(f)
with open("aggregation/templates/bribe_balancer.json") as f:
    BALANCER_BRIB = json.load(f)["transactions"][0]
with open("aggregation/templates/bribe_aura.json") as f:
    AURA_BRIB = json.load(f)["transactions"][0]
with open("aggregation/templates/approve.json") as f:
    APPROVE = json.load(f)
with open("aggregation/templates/erc20_transfer.json") as f:
    TRANSFER = json.load(f)


def get_abi(contract_name: str) -> Union[Dict, List[Dict]]:
    project_root_dir = os.path.abspath(os.path.dirname(__file__))
    with open(f"{project_root_dir}/abi/{contract_name}.json") as f:
        return json.load(f)


def get_hh_aura_target(target):
    response = requests.get(f"{HH_API_URL}/aura")
    options = response.json()["data"]
    for option in options:
        if Web3.to_checksum_address(option["proposal"]) == target:
            return option["proposalHash"]
    return False  # return false if no result


def get_gauge_name_map(map_url=GAUGE_MAPPING_URL):
    # the url was not responding on IPv6 addresses
    requests.packages.urllib3.util.connection.HAS_IPV6 = False
    response = requests.get(map_url)
    item_list = response.json()
    output = {}
    for mapping in item_list:
        gauge_address = Web3.to_checksum_address(mapping["address"])
        output[gauge_address] = mapping["label"]
    return output


def get_index(proposal_id, target):
    # grab data from the snapshot endpoint re proposal choices
    response = requests.post(
        SNAPSHOT_URL,
        json={
            "query": QUERY_PROPOSAL_INFO,
            "variables": {"proposal_id": proposal_id},
        },
    )
    choices = response.json()["data"]["proposal"]["choices"]
    choice = choices.index(target)
    return choice


def process_bribe_csv(csv_file):
    # Process the CSV
    # csv_format: target, platform, amount
    bribe_csv = list(csv.DictReader(open(csv_file)))
    bribes = {"aura": {}, "balancer": {}, "payment": {}}
    # Parse briibes per platform
    for bribe in bribe_csv:
        try:
            bribes[bribe["platform"]][bribe["target"]] = float(bribe["amount"])
        except Exception:
            assert (
                False
            ), f"Error: The following brib didn't work, somethings probs wrong: \b{bribe}"
    return bribes


def generate_payload(web3: Web3, week: str):
    csv_file = f"aggregation/outputs/{week}/{week}.csv"
    tx_list = []
    usdc = web3.eth.contract(
        address=address_book.extras.tokens.USDC,
        abi=get_abi("ERC20"),
    )
    usdc_decimals = usdc.functions.decimals().call()
    usdc_mantissa_multilpier = 10 ** int(usdc_decimals)

    bribe_vault = address_book.extras.hidden_hand2.bribe_vault
    bribes = process_bribe_csv(csv_file)

    # Calculate total bribe
    total_balancer_usdc = 0
    total_aura_usdc = 0
    for target, amount in bribes["balancer"].items():
        total_balancer_usdc += amount
    for target, amount in bribes["aura"].items():
        total_aura_usdc += amount
    total_usdc = total_balancer_usdc + total_aura_usdc
    total_mantissa = int(total_usdc * usdc_mantissa_multilpier)

    usdc_approve = copy.deepcopy(APPROVE)
    usdc_approve["to"] = address_book.extras.tokens.USDC
    usdc_approve["contractInputsValues"]["spender"] = bribe_vault
    usdc_approve["contractInputsValues"]["rawAmount"] = str(total_mantissa + 1)
    tx_list.append(usdc_approve)
    # Do Payments
    payments_usd = 0
    payments = 0
    for target, amount in bribes["payment"].items():
        print(f"Paying out {amount} via direct transfer to {target}")
        print(amount)
        usdc_amount = amount * 10**usdc_decimals
        print(usdc_amount)
        payments_usd += amount
        transfer = copy.deepcopy(TRANSFER)
        transfer["to"] = address_book.extras.tokens.USDC
        transfer["contractInputsValues"]["value"] = str(int(usdc_amount))
        print("----------------------------------")
        print(transfer["contractInputsValues"]["value"])
        transfer["contractInputsValues"]["to"] = target
        print(transfer["contractInputsValues"]["to"])
        tx_list.append(transfer)
        payments += usdc_amount

    # Print report
    print(f"******** Summary Report")
    print(f"*** Aura USDC: {total_aura_usdc}")
    print(f"*** Balancer USDC: {total_balancer_usdc}")
    print(f"*** Payment USDC: {payments_usd}")
    print(f"*** Total USDC: {total_usdc + payments_usd}")
    print(f"*** Total mantissa: {int(total_mantissa + payments)}")

    # BALANCER
    def bribe_balancer(gauge, mantissa):
        prop = Web3.solidity_keccak(["address"], [Web3.to_checksum_address(gauge)])
        mantissa = int(mantissa)

        print("******* Posting Balancer Bribe:")
        print("*** Gauge Address:", gauge)
        print("*** Proposal hash:", prop.hex())
        print("*** Amount:", amount)
        print("*** Mantissa Amount:", mantissa)

        if amount == 0:
            return
        bal_tx = copy.deepcopy(BALANCER_BRIB)
        bal_tx["contractInputsValues"]["_proposal"] = prop.hex()
        bal_tx["contractInputsValues"]["_token"] = address_book.extras.tokens.USDC
        bal_tx["contractInputsValues"]["_amount"] = str(mantissa)

        tx_list.append(bal_tx)

    for target, amount in bribes["balancer"].items():
        if amount == 0:
            continue
        mantissa = int(amount * usdc_mantissa_multilpier)
        bribe_balancer(target, mantissa)

    # AURA
    for target, amount in bribes["aura"].items():
        if amount == 0:
            continue
        target = Web3.to_checksum_address(target)
        # grab data from proposals to find out the proposal index
        prop = get_hh_aura_target(target)
        mantissa = int(amount * usdc_mantissa_multilpier)
        # NOTE: debugging prints to verify
        print("******* Posting AURA Bribe:")
        print("*** Target Gauge Address:", target)
        print("*** Proposal hash:", prop)
        print("*** Amount:", amount)
        print("*** Mantissa Amount:", mantissa)

        if amount == 0:
            return
        tx = copy.deepcopy(AURA_BRIB)
        tx["contractInputsValues"]["_proposal"] = prop
        tx["contractInputsValues"]["_token"] = address_book.extras.tokens.USDC
        tx["contractInputsValues"]["_amount"] = str(mantissa)
        tx_list.append(tx)

    bal = web3.eth.contract(
        address=address_book.extras.tokens.BAL,
        abi=get_abi("ERC20"),
    )

    spent_usdc = payments + total_mantissa
    print(spent_usdc)
    usdc_trasfer = copy.deepcopy(TRANSFER)
    usdc_trasfer["to"] = usdc.address
    usdc_trasfer["contractInputsValues"][
        "to"
    ] = address_book.extras.maxiKeepers.veBalFeeInjector
    usdc_trasfer["contractInputsValues"]["value"] = str(
        int(usdc.functions.balanceOf(safe).call() - spent_usdc)
    )
    tx_list.append(usdc_trasfer)
    bal_trasfer = TRANSFER
    bal_trasfer["to"] = address_book.extras.tokens.BAL
    bal_trasfer["contractInputsValues"][
        "to"
    ] = address_book.extras.maxiKeepers.veBalFeeInjector
    bal_trasfer["contractInputsValues"]["value"] = str(
        bal.functions.balanceOf(safe).call()
    )
    tx_list.append(bal_trasfer)
    print("\n\nBuilding and pushing multisig payload")
    print("saving payload")
    payload = PAYLOAD
    payload["meta"]["createdFromSafeAddress"] = safe
    payload["transactions"] = tx_list
    os.makedirs(f"aggregation/transactions/{week}", exist_ok=True)
    with open(f"aggregation/transactions/{week}/{week}.json", "w") as tx_file:
        json.dump(payload, tx_file)
    print(f"balance: {usdc.functions.balanceOf(safe).call()}")
    print(f"USDC to Bribs: {total_mantissa}")
    print(f"USDC payments: {payments}")
    print(f"USDC to veBAL: {usdc.functions.balanceOf(safe).call() - spent_usdc}")
    print(f"BAL to veBAL: {bal.functions.balanceOf(safe).call()}")
    print(f"Total USDC to pay: {total_mantissa + payments}")

