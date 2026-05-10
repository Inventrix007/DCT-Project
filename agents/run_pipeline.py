"""
run_pipeline.py
---------------
Entry point for the parallel DCT pipeline:

  1. Connect to Hardhat (local) or Sepolia testnet
  2. Human principal mints root MANAGE DCT for Manager
  3. Manager splits task -> two subtasks, mints CODE tokens for Coder A + B
  4. Coder A and Coder B run IN PARALLEL (threads)
  5. Manager mints TEST token for Tester
  6. Tester writes + runs integration tests on both modules
  7. Manager marks itself complete
  8. Full delegation audit trail printed from the blockchain

LOCAL (Hardhat):
  Terminal 1:  npx hardhat node
  Terminal 2:  npx hardhat run scripts/deploy.cjs --network localhost
               python agents/run_pipeline.py

SEPOLIA (testnet):
  npx hardhat run scripts/deploy.cjs --network sepolia
  NETWORK=sepolia python agents/run_pipeline.py
"""

import os
import sys, time
from concurrent.futures import ThreadPoolExecutor

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass  # python-dotenv optional; export vars manually for Sepolia

NETWORK = os.getenv("NETWORK", "local")

if NETWORK == "sepolia":
    RPC_URL  = os.environ["SEPOLIA_RPC_URL"]
    ACCOUNTS = {
        "deployer": {"address": os.environ["DEPLOYER_ADDRESS"],
                     "private_key": os.environ["DEPLOYER_PRIVATE_KEY"]},
        "manager":  {"address": os.environ["MANAGER_ADDRESS"],
                     "private_key": os.environ["MANAGER_PRIVATE_KEY"]},
        "coder1":   {"address": os.environ["CODER1_ADDRESS"],
                     "private_key": os.environ["CODER1_PRIVATE_KEY"]},
        "coder2":   {"address": os.environ["CODER2_ADDRESS"],
                     "private_key": os.environ["CODER2_PRIVATE_KEY"]},
        "tester":   {"address": os.environ["TESTER_ADDRESS"],
                     "private_key": os.environ["TESTER_PRIVATE_KEY"]},
    }
else:
    # Hardhat well-known test keys -- LOCAL ONLY, no real ETH
    RPC_URL  = os.getenv("HARDHAT_RPC_URL", "http://127.0.0.1:8545")
    ACCOUNTS = {
        "deployer": {"address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                     "private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"},
        "manager":  {"address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                     "private_key": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"},
        "coder1":   {"address": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
                     "private_key": "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"},
        "coder2":   {"address": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
                     "private_key": "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"},
        "tester":   {"address": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
                     "private_key": "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"},
    }

ABI_PATH = os.path.join(os.path.dirname(__file__), "..", "abi", "DelegationRegistry.json")

CODING_TASK = """
Build a Python module that implements a simple in-memory task queue with the
following requirements:
- A TaskQueue class with methods: enqueue(task), dequeue(), peek(), is_empty(), size()
- Tasks are strings
- dequeue() and peek() raise an IndexError if the queue is empty
- The queue should be FIFO (first in, first out)
- Include a method to list all current tasks without removing them
"""


def main():
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    print("LLM backend : Ollama (" + model + ")")
    print("Ensure Ollama is running:  ollama serve")
    print("And model is pulled:       ollama pull " + model + "\n")

    sys.path.insert(0, os.path.dirname(__file__))
    from dct_client   import DCTClient, SCOPE_MANAGE, SCOPE_TEST
    from manager_agent import ManagerAgent
    from coder_agent   import CoderAgent
    from tester_agent  import TesterAgent

    print("=" * 60)
    print("  DCT PIPELINE -- Parallel AI Agents + Blockchain Audit")
    print("  Network: " + NETWORK.upper())
    print("=" * 60)
    print("Connecting to " + RPC_URL[:40] + "...")

    deployer_client = DCTClient(RPC_URL, ACCOUNTS["deployer"]["private_key"], ABI_PATH)
    manager_client  = DCTClient(RPC_URL, ACCOUNTS["manager"]["private_key"],  ABI_PATH)
    coder1_client   = DCTClient(RPC_URL, ACCOUNTS["coder1"]["private_key"],   ABI_PATH)
    coder2_client   = DCTClient(RPC_URL, ACCOUNTS["coder2"]["private_key"],   ABI_PATH)
    tester_client   = DCTClient(RPC_URL, ACCOUNTS["tester"]["private_key"],   ABI_PATH)

    print("Connected. Tokens on chain: " + str(deployer_client.total_tokens()))

    if NETWORK == "sepolia":
        print("Contract: https://sepolia.etherscan.io/address/"
              + str(deployer_client.contract.address))

    # Step 1: mint root MANAGE token
    print("\n[Human] Minting root MANAGE token for Manager...")
    manager_token_id = deployer_client.mint_root(
        delegatee_address=ACCOUNTS["manager"]["address"],
        scope=SCOPE_MANAGE,
        task_description=CODING_TASK.strip()[:200],
    )

    # Step 2: Manager splits task, delegates CODE to Coder A + B
    manager = ManagerAgent(manager_client, manager_token_id)
    spec_a, coder1_token_id, spec_b, coder2_token_id = manager.plan_and_split(
        user_task=CODING_TASK,
        coder1_address=ACCOUNTS["coder1"]["address"],
        coder2_address=ACCOUNTS["coder2"]["address"],
    )

    # Step 3: Coder A and Coder B run IN PARALLEL
    print("\n[Pipeline] Launching Coder A (token #" + str(coder1_token_id) +
          ") and Coder B (token #" + str(coder2_token_id) + ") in parallel...")

    coder_a = CoderAgent(coder1_client, coder1_token_id, label="Coder A")
    coder_b = CoderAgent(coder2_client, coder2_token_id, label="Coder B")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(coder_a.write_code, spec_a)
        future_b = executor.submit(coder_b.write_code, spec_b)
        code_a = future_a.result()
        code_b = future_b.result()
    time.sleep(3)

    print("\n[Pipeline] Both coders finished.")
    print("  module_a: " + str(len(code_a)) + " chars")
    print("  module_b: " + str(len(code_b)) + " chars")

    # Step 4: Manager delegates TEST token
    print("\n[ManagerAgent] Delegating TEST token to Tester...")
    tester_token_id = manager_client.delegate(
        parent_token_id=manager_token_id,
        delegatee_address=ACCOUNTS["tester"]["address"],
        scope=SCOPE_TEST,
        task_description="Integration test module_a.py and module_b.py",
        fund_amount_eth=0.01,
    )
    manager_client.record_action(
        manager_token_id, "DELEGATED_TO_TESTER",
        "Token #" + str(tester_token_id) + " -> tester " + ACCOUNTS["tester"]["address"][:16]
    )

    # Step 5: Tester runs integration tests
    tester = TesterAgent(tester_client, tester_token_id)
    result = tester.run(code_a=code_a, code_b=code_b, spec_a=spec_a, spec_b=spec_b)

    # Step 6: Manager marks itself complete
    manager.finish()

    # Step 7: Print audit trail
    deployer_client.print_audit_trail(tester_token_id)

    if NETWORK == "sepolia":
        print("\nView on Etherscan:")
        print("https://sepolia.etherscan.io/address/" + str(deployer_client.contract.address))

    print("\n  PIPELINE COMPLETE")
    print("  Tests         : " + result["summary"])
    print("  DCTs minted   : " + str(deployer_client.total_tokens()))
    print("  Actions logged: " + str(len(deployer_client.get_all_actions())))
    print("=" * 60)
    return result


if __name__ == "__main__":
    main()
