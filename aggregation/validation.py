# Create dataclass for CSV payload validation
from dataclasses import dataclass
from web3 import Web3

PLATFORMS = ["aura", "balancer", "payment"]


class ValidationError(Exception):
    pass


@dataclass
class Transaction:
    target: str
    platform: str
    amount: float

    def __post_init__(self):
        # Validate target is a valid Ethereum address
        if not Web3.is_address(self.target):
            raise ValidationError(f"Invalid target address: {self.target}")
        # Normalize target address
        self.target = Web3.to_checksum_address(self.target)
        # Platform validation
        if self.platform not in PLATFORMS:
            raise ValidationError(f"Invalid platform: {self.platform}")

        # Amount validation
        if self.amount < 0:
            raise ValidationError(f"Invalid amount: {self.amount}")
