"""
coder_agent.py
--------------
Writes Python code for one subtask (module_a.py or module_b.py).
Designed to run in parallel with a second CoderAgent instance.

Blockchain role:
  - Holds a CODE-scoped DCT (issued by Manager)
  - Records implementation steps on-chain
  - Marks its own token complete when done
  - Does NOT sub-delegate (Manager handles Tester delegation)
"""

import os
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from dct_client import DCTClient

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = """You are the Coder Agent in a multi-agent software pipeline.

You receive a technical specification and must implement it as clean Python code.

Rules:
- Write complete, runnable Python code
- Include all necessary imports
- Add docstrings to all functions and classes
- Handle edge cases mentioned in the spec
- Do NOT include test code
- Your module will be saved as module_a.py or module_b.py

Your output MUST be structured as:
---CODE---
<complete Python code, nothing else inside this block>
---END_CODE---
---NOTES---
<implementation notes>"""


class CoderAgent:
    def __init__(self, chain_client: DCTClient, coder_token_id: int,
                 label: str = "Coder", llm=None):
        self.client   = chain_client
        self.token_id = coder_token_id
        self.label    = label
        self.llm      = llm or ChatOllama(model=OLLAMA_MODEL)

    def write_code(self, spec: str) -> str:
        """Write code from spec, record on-chain, complete token. Returns code."""
        print("\n" + "-" * 50)
        print("[" + self.label + "] Starting implementation. Token: #" + str(self.token_id))

        self.client.record_action(
            self.token_id, "STARTED_IMPLEMENTATION",
            "Received spec (" + str(len(spec)) + " chars)"
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content="Here is your specification:\n\n" + spec)
        ]

        code = ""
        for attempt in range(2):
            response   = self.llm.invoke(messages)
            raw_output = response.content
            code       = self._extract_code(raw_output)
            if code:
                break
            print("[" + self.label + "] Warning: missing ---CODE--- markers (attempt "
                  + str(attempt + 1) + "), retrying...")
            messages.append(HumanMessage(content=(
                "Your response was missing the ---CODE--- / ---END_CODE--- markers. "
                "Please respond again wrapped exactly as:\n"
                "---CODE---\n<your code>\n---END_CODE---"
            )))

        print("[" + self.label + "] Code written (" + str(len(code)) + " chars)")

        self.client.record_action(
            self.token_id, "WROTE_CODE",
            "Written " + str(len(code)) + " chars. Preview: " + code[:150]
        )

        self.client.complete(self.token_id)
        print("[" + self.label + "] Token #" + str(self.token_id) + " marked complete.")
        return code

    def _extract_code(self, raw: str) -> str:
        if "---CODE---" in raw and "---END_CODE---" in raw:
            return raw.split("---CODE---")[1].split("---END_CODE---")[0].strip()
        if "```python" in raw:
            return raw.split("```python")[1].split("```")[0].strip()
        if "```" in raw:
            return raw.split("```")[1].split("```")[0].strip()
        return raw.strip()
