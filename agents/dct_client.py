"""
dct_client.py
─────────────
Web3 wrapper that gives LangChain agents a clean interface to the
DelegationRegistry smart contract running on a local Hardhat node
or Sepolia testnet.

Scope enum mirrors the Solidity contract:
    MANAGE = 0, CODE = 1, TEST = 2
"""

import json
import os
from pathlib import Path
from typing import Optional
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# Scope constants (must match Solidity enum order)
SCOPE_MANAGE = 0
SCOPE_CODE   = 1
SCOPE_TEST   = 2

SCOPE_NAMES = {0: "MANAGE", 1: "CODE", 2: "TEST"}


class DCTClient:
    """
    Thin wrapper around the DelegationRegistry contract.
    Each agent instantiates this with its own private key so txs are
    signed as the correct on-chain identity.
    """

    def __init__(self, rpc_url: str, private_key: str, abi_path: Optional[str] = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        # POA middleware needed for Hardhat / Sepolia
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to node at {rpc_url}")

        self.account = self.w3.eth.account.from_key(private_key)
        self.address = self.account.address

        # __file__ is inside agents/; root abi/ is one level up
        abi_path = abi_path or str(
            Path(__file__).parent.parent / "abi" / "DelegationRegistry.json"
        )
        with open(abi_path) as f:
            artifact = json.load(f)

        contract_address = Web3.to_checksum_address(artifact["address"])
        self.contract = self.w3.eth.contract(
            address=contract_address,
            abi=artifact["abi"],
        )

    # ── Internal tx helper ─────────────────────────────────────────────────

    def _send(self, fn):
        """Build, sign, and send a contract transaction. Returns receipt."""
        nonce = self.w3.eth.get_transaction_count(self.address, "pending")
        tx = fn.build_transaction({
            "from":     self.address,
            "nonce":    nonce,
            "gas":      1_000_000,
            "gasPrice": self.w3.eth.gas_price,
        })
        signed  = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

        if receipt["status"] == 0:
            revert_reason = "unknown"
            try:
                fn.call({"from": self.address})
            except Exception as e:
                revert_reason = str(e)
            print(f"[chain] REVERT tx={tx_hash.hex()[:20]}")
            print(f"[chain] REVERT reason={revert_reason}")
            raise RuntimeError(f"Transaction reverted: {revert_reason}")

        return receipt

    # ── Gas provisioning ──────────────────────────────────────────────────

    def fund_agent(self, recipient_address: str, amount_eth: float = 0.02) -> None:
        """Transfer ETH to an agent wallet before delegating to it."""
        recipient   = Web3.to_checksum_address(recipient_address)
        balance     = self.w3.eth.get_balance(recipient)
        min_balance = self.w3.to_wei(0.0005, "ether")

        if balance >= min_balance:
            print(f"[chain] fund_agent skipped — {recipient_address[:10]} "
                  f"already has {self.w3.from_wei(balance, 'ether'):.4f} ETH")
            return

        tx = {
            "to":       recipient,
            "value":    self.w3.to_wei(amount_eth, "ether"),
            "gas":      21_000,
            "gasPrice": self.w3.eth.gas_price,
            "nonce":    self.w3.eth.get_transaction_count(self.address, "pending"),
            "chainId":  self.w3.eth.chain_id,
        }
        signed   = self.w3.eth.account.sign_transaction(tx, self.account.key)
        tx_hash  = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"[chain] fund_agent -> sent {amount_eth} ETH to {recipient_address[:10]}")

    # ── Delegation actions ────────────────────────────────────────────────

    def mint_root(self, delegatee_address: str, scope: int,
                  task_description: str, expires_at: int = 0,
                  fund_amount_eth: float = 0.2) -> int:
        """Human principal mints the root DCT for the Manager agent."""
        self.fund_agent(delegatee_address, fund_amount_eth)
        delegatee = Web3.to_checksum_address(delegatee_address)
        fn = self.contract.functions.mintRoot(
            delegatee, scope, task_description, expires_at
        )
        receipt  = self._send(fn)
        token_id = self._parse_token_id(receipt, delegatee_address)
        print(f"[chain] mintRoot -> token #{token_id} "
              f"({SCOPE_NAMES[scope]}) for {delegatee_address[:10]}")
        return token_id

    def delegate(self, parent_token_id: int, delegatee_address: str, scope: int,
                 task_description: str, expires_at: int = 0,
                 fund_amount_eth: float = 0.02) -> int:
        """An agent sub-delegates authority to another agent."""
        self.fund_agent(delegatee_address, fund_amount_eth)
        delegatee = Web3.to_checksum_address(delegatee_address)
        fn = self.contract.functions.delegate(
            parent_token_id, delegatee, scope, task_description, expires_at
        )
        receipt  = self._send(fn)
        token_id = self._parse_token_id(receipt, delegatee_address)
        print(f"[chain] delegate -> token #{token_id} "
              f"({SCOPE_NAMES[scope]}) parent=#{parent_token_id} "
              f"for {delegatee_address[:10]}")
        return token_id

    def record_action(self, token_id: int, action_type: str, details: str) -> None:
        """Log an agent action against its active token."""
        fn = self.contract.functions.recordAction(token_id, action_type, details)
        self._send(fn)
        print(f"[chain] recordAction token=#{token_id} type={action_type}")

    def complete(self, token_id: int) -> None:
        """Mark a token completed when the agent finishes its work."""
        fn = self.contract.functions.complete(token_id)
        self._send(fn)
        print(f"[chain] complete token=#{token_id}")

    def revoke(self, token_id: int) -> None:
        fn = self.contract.functions.revoke(token_id)
        self._send(fn)
        print(f"[chain] revoke token=#{token_id}")

    def _parse_token_id(self, receipt, delegatee_address: str) -> int:
        """
        Extract the minted token ID from a tx receipt.
        Tries three methods: ABI decode, raw log topic, delegatee token list.
        """
        try:
            logs = self.contract.events.Delegated().process_receipt(receipt)
            if logs:
                return logs[0]["args"]["tokenId"]
        except Exception:
            pass

        try:
            topic = self.w3.keccak(
                text="Delegated(uint256,uint256,address,address,uint8,string)"
            )
            for log in receipt["logs"]:
                if log["topics"][0] == topic:
                    token_id = int(log["topics"][1].hex(), 16)
                    print(f"[chain] token ID parsed from raw log: #{token_id}")
                    return token_id
        except Exception:
            pass

        checksum = Web3.to_checksum_address(delegatee_address)
        tokens   = self.contract.functions.getAgentTokens(checksum).call()
        if tokens:
            print(f"[chain] token ID from agent token list: #{tokens[-1]}")
            return tokens[-1]

        raise RuntimeError("Could not determine minted token ID from receipt")

    # ── Read / audit ──────────────────────────────────────────────────────

    def get_chain(self, token_id: int) -> list:
        raw = self.contract.functions.getChain(token_id).call()
        return [self._parse_dct(t) for t in raw]

    def get_child_tokens(self, parent_id: int) -> list:
        """Return direct child token IDs for a given parent (O(1) lookup)."""
        return self.contract.functions.getChildTokens(parent_id).call()

    def get_token_actions(self, token_id: int) -> list:
        raw = self.contract.functions.getTokenActions(token_id).call()
        return [self._parse_action(a) for a in raw]

    def get_all_actions(self) -> list:
        raw = self.contract.functions.getAllActions().call()
        return [self._parse_action(a) for a in raw]

    def get_agent_tokens(self, address: str) -> list:
        return self.contract.functions.getAgentTokens(
            Web3.to_checksum_address(address)
        ).call()

    def total_tokens(self) -> int:
        return self.contract.functions.totalTokens().call()

    # ── Parsers ───────────────────────────────────────────────────────────

    def _parse_dct(self, t) -> dict:
        return {
            "id":              t[0],
            "parentId":        t[1],
            "delegator":       t[2],
            "delegatee":       t[3],
            "scope":           SCOPE_NAMES.get(t[4], t[4]),
            "taskDescription": t[5],
            "issuedAt":        t[6],
            "expiresAt":       t[7],
            "revoked":         t[8],
            "completed":       t[9],
        }

    def _parse_action(self, a) -> dict:
        return {
            "tokenId":    a[0],
            "agent":      a[1],
            "actionType": a[2],
            "details":    a[3],
            "timestamp":  a[4],
        }

    # ── Pretty audit report ───────────────────────────────────────────────

    def print_audit_trail(self, leaf_token_id: int) -> None:
        """Print a human-readable audit trail for a full delegation chain."""
        sep = "=" * 60
        print("\n" + sep)
        print("  DELEGATION AUDIT TRAIL")
        print(sep)

        chain = self.get_chain(leaf_token_id)
        for i, dct in enumerate(chain):
            ind  = "  " * i
            ind1 = "  " * (i + 1)
            ind2 = "  " * (i + 2)
            prefix = ind + ("|-- " if i > 0 else "")
            if dct["completed"]:
                status = "[completed]"
            elif dct["revoked"]:
                status = "[revoked]"
            else:
                status = "[active]"
            print(prefix + "[Token #" + str(dct["id"]) + "] "
                  + dct["scope"] + " | " + status)
            print(ind1 + "delegator: " + dct["delegator"][:20])
            print(ind1 + "delegatee: " + dct["delegatee"][:20])
            print(ind1 + "task:      " + dct["taskDescription"])

            actions = self.get_token_actions(dct["id"])
            if actions:
                print(ind1 + "actions:")
                for a in actions:
                    print(ind2 + "[" + a["actionType"] + "] " + a["details"][:80])
            print()

        print(sep)
