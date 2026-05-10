"""
manager_agent.py
----------------
The Manager Agent receives a coding task from the human principal,
splits it into two independent subtasks, and sub-delegates each to a
separate Coder Agent (enabling parallel execution).

Blockchain role:
  - Holds a MANAGE-scoped DCT (minted by human)
  - Mints two CODE-scoped child DCTs (one per coder)
  - Records its planning actions on-chain
  - Marks its own token complete after all children finish
"""

import os
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from dct_client import DCTClient, SCOPE_CODE

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = """You are the Manager Agent in a multi-agent software pipeline.

Your job:
1. Receive a coding task from the user
2. Split it into EXACTLY TWO independent, parallel subtasks (Module A and Module B)
3. Each subtask must be implementable as a standalone Python module
4. Define a clear interface so the two modules can work together

Rules for splitting:
- The two subtasks must be independent (no circular dependencies)
- Each module should handle a distinct, well-scoped concern
- Define any shared data structures or interfaces explicitly

Your output MUST follow this structure exactly:
---SUBTASK_A---
<complete technical specification for Module A, including function signatures,
expected behavior, edge cases, module filename: module_a.py>
---END_SUBTASK_A---
---SUBTASK_B---
<complete technical specification for Module B, including function signatures,
expected behavior, edge cases, module filename: module_b.py>
---END_SUBTASK_B---
---INTERFACE---
<description of how Module A and Module B interact or complement each other>
---TASK_SUMMARY---
<one sentence describing the overall system being built>

Be precise. The Coder Agents will implement exactly what you specify."""


class ManagerAgent:
    def __init__(self, chain_client: DCTClient, manager_token_id: int, llm=None):
        self.client   = chain_client
        self.token_id = manager_token_id
        self.llm      = llm or ChatOllama(model=OLLAMA_MODEL)

    def plan_and_split(self, user_task: str, coder1_address: str,
                       coder2_address: str) -> tuple:
        """
        Plan the task, split into two subtasks, issue CODE DCTs to two coders.
        Returns: (spec_a, coder1_token_id, spec_b, coder2_token_id)
        """
        print("\n" + "-" * 50)
        print("[ManagerAgent] Received task: " + user_task[:80])
        print("[ManagerAgent] Token: #" + str(self.token_id))

        self.client.record_action(
            self.token_id, "RECEIVED_TASK", "Task: " + user_task[:200]
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content="Split this coding task into two independent parallel subtasks:\n\n" + user_task)
        ]
        response    = self.llm.invoke(messages)
        plan_output = response.content

        print("[ManagerAgent] Plan generated, splitting into 2 subtasks...")

        spec_a, spec_b = self._extract_specs(plan_output)

        self.client.record_action(
            self.token_id, "CREATED_SPLIT_PLAN", plan_output[:200]
        )

        task_summary = user_task[:200]
        if "---TASK_SUMMARY---" in plan_output:
            task_summary = plan_output.split("---TASK_SUMMARY---")[-1].strip()[:200]

        coder1_token_id = self.client.delegate(
            parent_token_id=self.token_id,
            delegatee_address=coder1_address,
            scope=SCOPE_CODE,
            task_description="[Module A] " + task_summary,
            fund_amount_eth=0.02,
        )
        self.client.record_action(
            self.token_id, "DELEGATED_TO_CODER_A",
            "Token #" + str(coder1_token_id) + " -> coder_a " + coder1_address[:16]
        )

        coder2_token_id = self.client.delegate(
            parent_token_id=self.token_id,
            delegatee_address=coder2_address,
            scope=SCOPE_CODE,
            task_description="[Module B] " + task_summary,
            fund_amount_eth=0.02,
        )
        self.client.record_action(
            self.token_id, "DELEGATED_TO_CODER_B",
            "Token #" + str(coder2_token_id) + " -> coder_b " + coder2_address[:16]
        )

        print("[ManagerAgent] Delegated token #" + str(coder1_token_id) + " -> Coder A (parallel)")
        print("[ManagerAgent] Delegated token #" + str(coder2_token_id) + " -> Coder B (parallel)")

        return spec_a, coder1_token_id, spec_b, coder2_token_id

    def finish(self) -> None:
        """Mark the manager token complete after all children are done."""
        self.client.complete(self.token_id)
        print("[ManagerAgent] Token #" + str(self.token_id) + " marked complete.")

    def _extract_specs(self, raw: str) -> tuple:
        """Extract spec_a and spec_b from the LLM output."""
        spec_a, spec_b = "", ""

        if "---SUBTASK_A---" in raw and "---END_SUBTASK_A---" in raw:
            spec_a = raw.split("---SUBTASK_A---")[1].split("---END_SUBTASK_A---")[0].strip()
        if "---SUBTASK_B---" in raw and "---END_SUBTASK_B---" in raw:
            spec_b = raw.split("---SUBTASK_B---")[1].split("---END_SUBTASK_B---")[0].strip()

        if not spec_a:
            spec_a = raw.strip()
        if not spec_b:
            spec_b = ("Implement a complementary utility module (module_b.py) that "
                      "provides helper functions and validation for module_a.py.")
        return spec_a, spec_b
