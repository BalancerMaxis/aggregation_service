import csv
import os

from web3 import Web3

from aggregation.validation import Transaction


def process_payloads(week: str) -> None:
    """
    Entry point function that parses target week and runs the pipeline.
    Saves the processed data to the gnosis SAFE transaction JSON
    """

    # TODO: First: validate each file to comply with the schema
    # Find all CSV files in inputs/week directory:
    transactions = {}
    for file in os.listdir(f"aggregation/inputs/{week}"):
        if not file.endswith(".csv"):
            continue

        with open(f"aggregation/inputs/{week}/{file}") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (Web3.to_checksum_address(row['target']), row['platform'])
                amount = float(row['amount'])

                if key in transactions:
                    transactions[key].amount += amount
                else:
                    transactions[key] = Transaction(
                        target=row['target'],
                        platform=row['platform'],
                        amount=amount
                    )
    # Now save transactions into outputs/week directory in CSV format
    os.makedirs(f"aggregation/outputs/{week}", exist_ok=True)
    with open(f"aggregation/outputs/{week}/{week}.csv", "w") as f:
        writer = csv.DictWriter(f, fieldnames=["target", "platform", "amount"])
        writer.writeheader()
        for transaction in transactions.values():
            writer.writerow({
                "target": transaction.target,
                "platform": transaction.platform,
                "amount": transaction.amount
            })
