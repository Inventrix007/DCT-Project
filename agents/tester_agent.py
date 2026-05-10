"""
tester_agent.py
---------------
Receives two implemented modules and writes + runs an integration test suite.

Blockchain role:
  - Holds a TEST-scoped DCT (issued by Manager after both coders finish)
  - Cannot sub-delegate (TEST is the narrowest scope)
  - Records test results on-chain
  - Marks its token complete when done
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path
import os
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from dct_client import DCTClient

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SYSTEM_PROMPT = """You are the Tester Agent in a multi-agent software pipeline.

You receive TWO Python modules from parallel Coder Agents and must write a
comprehensive pytest test suite covering both.

The two modules are:
  - module_a.py  (Module A)
  - module_b.py  (Module B)

Rules:
- Write pytest-style test functions (def test_...)
- Import from both: use `from module_a import *` and `from module_b import *`
- Test each module independently AND how they integrate
- Test normal cases, edge cases, and error cases
- Do NOT redefine any functions from the modules

Your output MUST be structured as:
---TESTS---
<complete pytest test file>
---END_TESTS---
---TEST_PLAN---
<brief description of what you are testing and why>"""


class TesterAgent:
    def __init__(self, chain_client: DCTClient, tester_token_id: int, llm=None):
        self.client   = chain_client
        self.token_id = tester_token_id
        self.llm      = llm or ChatOllama(model=OLLAMA_MODEL)

    def run(self, code_a: str, code_b: str, spec_a: str, spec_b: str) -> dict:
        """Write and run integration tests for both modules. Returns result dict."""
        print("\n" + "-" * 50)
        print("[TesterAgent] Starting integration test phase. Token: #" + str(self.token_id))

        self.client.record_action(
            self.token_id, "STARTED_TESTING",
            "module_a (" + str(len(code_a)) + " chars) + module_b (" + str(len(code_b)) + " chars)"
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=(
                "Module A spec:\n" + spec_a + "\n\n"
                "Module A code (module_a.py):\n```python\n" + code_a + "\n```\n\n"
                "Module B spec:\n" + spec_b + "\n\n"
                "Module B code (module_b.py):\n```python\n" + code_b + "\n```\n\n"
                "Write a comprehensive integration test suite for both modules."
            ))
        ]

        test_code = ""
        for attempt in range(2):
            response   = self.llm.invoke(messages)
            raw_output = response.content
            test_code  = self._extract_tests(raw_output)
            if test_code:
                break
            print("[TesterAgent] Warning: missing ---TESTS--- markers (attempt "
                  + str(attempt + 1) + "), retrying...")
            messages.append(HumanMessage(content=(
                "Your response was missing the ---TESTS--- / ---END_TESTS--- markers. "
                "Please respond again wrapped exactly as:\n"
                "---TESTS---\n<your tests>\n---END_TESTS---"
            )))

        print("[TesterAgent] Tests generated (" + str(len(test_code)) + " chars)")

        self.client.record_action(
            self.token_id, "WROTE_TESTS",
            "Generated " + str(len(test_code)) + " chars of integration test code"
        )

        result = self._run_tests(code_a, code_b, test_code)

        status  = "PASS" if result["failed"] == 0 and result["errors"] == 0 else "FAIL"
        summary = (status + ": " + str(result["passed"]) + " passed, "
                   + str(result["failed"]) + " failed, " + str(result["errors"]) + " errors")

        self.client.record_action(
            self.token_id, "TEST_RESULT_" + status,
            summary + " | Output: " + result["output"][:120]
        )

        print("\n[TesterAgent] " + summary)
        print("[TesterAgent] Test output:\n" + result["output"])

        self.client.complete(self.token_id)

        result["test_code"] = test_code
        result["summary"]   = summary
        return result

    def _run_tests(self, code_a: str, code_b: str, test_code: str) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "module_a.py").write_text(code_a)
            (tmp / "module_b.py").write_text(code_b)
            (tmp / "test_integration.py").write_text(test_code)

            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "test_integration.py",
                 "-v", "--tb=short", "--no-header"],
                cwd=tmpdir, capture_output=True, text=True, timeout=60,
            )

        output = proc.stdout + proc.stderr
        return {
            "passed":     self._parse_count(output, "passed"),
            "failed":     self._parse_count(output, "failed"),
            "errors":     self._parse_count(output, "error"),
            "output":     output,
            "returncode": proc.returncode,
        }

    def _parse_count(self, output: str, keyword: str) -> int:
        match = re.search(r"(\d+)\s+" + keyword, output)
        return int(match.group(1)) if match else 0

    def _extract_tests(self, raw: str) -> str:
        if "---TESTS---" in raw and "---END_TESTS---" in raw:
            return raw.split("---TESTS---")[1].split("---END_TESTS---")[0].strip()
        if "```python" in raw:
            return raw.split("```python")[1].split("```")[0].strip()
        if "```" in raw:
            return raw.split("```")[1].split("```")[0].strip()
        return raw.strip()
