"""
demo_run.py
-----------
Self-contained demo: runs the full DCT pipeline against a live Hardhat node.
Uses STUB LLM responses (no Ollama needed) so it runs offline in any environment.

Pipeline:
  [Human]   mintRoot MANAGE  -> Manager (token #1)
  [Manager] delegate CODE    -> Coder A  (token #2)
  [Manager] delegate CODE    -> Coder B  (token #3)
  [Coder A] recordAction x2, complete   (parallel with Coder B)
  [Coder B] recordAction x2, complete   (parallel with Coder A)
  [Manager] delegate TEST    -> Tester   (token #4)
  [Tester]  recordAction x3, complete
  [Manager] complete
  Print full on-chain audit trail
"""

import os, sys, json, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── locate project root ─────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
ABI_PATH = ROOT / "abi" / "DelegationRegistry.json"

sys.path.insert(0, str(Path(__file__).parent))
from dct_client import DCTClient, SCOPE_MANAGE, SCOPE_CODE, SCOPE_TEST

# ── Hardhat well-known accounts ─────────────────────────────────────────────
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

# ── stub LLM outputs ─────────────────────────────────────────────────────────
SPEC_A = "Implement TaskQueue.enqueue(), dequeue(), peek(), is_empty(), size(), list_tasks(). FIFO. Raise IndexError on dequeue/peek if empty."
SPEC_B = "Implement TaskQueue.clear() and TaskQueue.transfer(other) — transfers all tasks from self to another queue. Reuse TaskQueue from module_a."
CODE_A = '''
from collections import deque

class TaskQueue:
    """FIFO task queue backed by a deque."""
    def __init__(self):
        self._q = deque()
    def enqueue(self, task: str):
        """Add task to the back."""
        self._q.append(task)
    def dequeue(self) -> str:
        """Remove and return the front task."""
        if not self._q:
            raise IndexError("dequeue from empty queue")
        return self._q.popleft()
    def peek(self) -> str:
        """Return front task without removing it."""
        if not self._q:
            raise IndexError("peek at empty queue")
        return self._q[0]
    def is_empty(self) -> bool:
        return len(self._q) == 0
    def size(self) -> int:
        return len(self._q)
    def list_tasks(self) -> list:
        return list(self._q)
'''.strip()
CODE_B = '''
from module_a import TaskQueue

def clear(q: TaskQueue):
    """Remove all tasks from q."""
    while not q.is_empty():
        q.dequeue()

def transfer(src: TaskQueue, dst: TaskQueue):
    """Move every task from src into dst, preserving order."""
    while not src.is_empty():
        dst.enqueue(src.dequeue())
'''.strip()
TEST_RESULT = "PASS: 8 passed, 0 failed, 0 errors"


def run_coder(client: DCTClient, token_id: int, label: str, spec: str, code: str) -> str:
    print(f"\n  [{label}] token #{token_id} -- starting implementation")
    client.record_action(token_id, "STARTED_IMPLEMENTATION",
                         f"Received spec ({len(spec)} chars)")
    time.sleep(0.3)   # simulate LLM latency
    client.record_action(token_id, "WROTE_CODE",
                         f"Written {len(code)} chars. Preview: {code[:80]}")
    client.complete(token_id)
    print(f"  [{label}] token #{token_id} -- COMPLETE")
    return code


def main():
    print("=" * 60)
    print("  DCT PIPELINE DEMO  --  Stub LLM + Live Hardhat")
    print("  Network : LOCAL (Hardhat)")
    print("=" * 60)

    deployer_client = DCTClient(RPC_URL, ACCOUNTS["deployer"]["private_key"], str(ABI_PATH))
    manager_client  = DCTClient(RPC_URL, ACCOUNTS["manager"]["private_key"],  str(ABI_PATH))
    coder1_client   = DCTClient(RPC_URL, ACCOUNTS["coder1"]["private_key"],   str(ABI_PATH))
    coder2_client   = DCTClient(RPC_URL, ACCOUNTS["coder2"]["private_key"],   str(ABI_PATH))
    tester_client   = DCTClient(RPC_URL, ACCOUNTS["tester"]["private_key"],   str(ABI_PATH))

    print(f"\nConnected. Tokens on chain: {deployer_client.total_tokens()}")
    print(f"Contract : {deployer_client.contract.address}")

    # ── Step 1: Human mints root MANAGE token for Manager ────────────────────
    print("\n[Human Principal] Minting root MANAGE token for Manager...")
    mgr_tok = deployer_client.mint_root(
        delegatee_address=ACCOUNTS["manager"]["address"],
        scope=SCOPE_MANAGE,
        task_description="Build a Python in-memory task queue (FIFO) with full CRUD ops",
    )
    print(f"  => Manager token #{mgr_tok} minted")

    # ── Step 2: Manager records task receipt and splits work ──────────────────
    print("\n[Manager] Splitting task and delegating to Coder A + B...")
    manager_client.record_action(mgr_tok, "RECEIVED_TASK",
                                 "Task: build Python FIFO task queue")
    manager_client.record_action(mgr_tok, "CREATED_SPLIT_PLAN",
                                 "Subtask A: core queue class | Subtask B: clear+transfer helpers")

    coder1_tok = manager_client.delegate(
        parent_token_id=mgr_tok,
        delegatee_address=ACCOUNTS["coder1"]["address"],
        scope=SCOPE_CODE,
        task_description=SPEC_A[:200],
    )
    manager_client.record_action(mgr_tok, "DELEGATED_TO_CODER_A",
                                 f"Token #{coder1_tok} -> {ACCOUNTS['coder1']['address'][:16]}")

    coder2_tok = manager_client.delegate(
        parent_token_id=mgr_tok,
        delegatee_address=ACCOUNTS["coder2"]["address"],
        scope=SCOPE_CODE,
        task_description=SPEC_B[:200],
    )
    manager_client.record_action(mgr_tok, "DELEGATED_TO_CODER_B",
                                 f"Token #{coder2_tok} -> {ACCOUNTS['coder2']['address'][:16]}")

    print(f"  => Coder A token #{coder1_tok}, Coder B token #{coder2_tok}")

    # ── Step 3: Coder A and Coder B run IN PARALLEL ────────────────────────
    print(f"\n[Pipeline] Launching Coder A (#{coder1_tok}) and Coder B (#{coder2_tok}) in parallel...")

    with ThreadPoolExecutor(max_workers=2) as ex:
        fa = ex.submit(run_coder, coder1_client, coder1_tok, "Coder A", SPEC_A, CODE_A)
        fb = ex.submit(run_coder, coder2_client, coder2_tok, "Coder B", SPEC_B, CODE_B)
        code_a = fa.result()
        code_b = fb.result()

    print("\n[Pipeline] Both coders finished.")
    print(f"  module_a : {len(code_a)} chars")
    print(f"  module_b : {len(code_b)} chars")

    # ── Step 4: Manager delegates TEST token to Tester ────────────────────
    print("\n[Manager] Delegating TEST token to Tester...")
    tester_tok = manager_client.delegate(
        parent_token_id=mgr_tok,
        delegatee_address=ACCOUNTS["tester"]["address"],
        scope=SCOPE_TEST,
        task_description="Integration-test module_a.py and module_b.py",
    )
    manager_client.record_action(mgr_tok, "DELEGATED_TO_TESTER",
                                 f"Token #{tester_tok} -> {ACCOUNTS['tester']['address'][:16]}")
    print(f"  => Tester token #{tester_tok}")

    # ── Step 5: Tester runs tests ─────────────────────────────────────────
    print(f"\n[Tester] token #{tester_tok} -- running integration tests...")
    tester_client.record_action(tester_tok, "STARTED_TESTING",
                                f"module_a ({len(code_a)} chars) + module_b ({len(code_b)} chars)")
    time.sleep(0.3)
    tester_client.record_action(tester_tok, "WROTE_TESTS",
                                "Generated 42 lines of pytest integration tests")
    tester_client.record_action(tester_tok, "TEST_RESULT_PASS", TEST_RESULT)
    tester_client.complete(tester_tok)
    print(f"  [Tester] {TEST_RESULT}")

    # ── Step 6: Manager marks itself complete ─────────────────────────────
    print("\n[Manager] Marking complete...")
    manager_client.complete(mgr_tok)
    print("  => Manager token #1 COMPLETE")

    # ── Step 7: Full audit trail from blockchain ──────────────────────────
    print()
    deployer_client.print_audit_trail(tester_tok)

    total_tokens  = deployer_client.total_tokens()
    total_actions = len(deployer_client.get_all_actions())
    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    print(f"  DCTs minted   : {total_tokens}")
    print(f"  Actions logged: {total_actions}")
    print(f"  Test result   : {TEST_RESULT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
