"""Comment-Driven LLM Judge — evaluates whether flagged issues are fixed.

Instead of a fixed rubric, the judge evaluates the NEW agent response
against the human's SPECIFIC comment about what was wrong with the
original response.

Usage:
    from tests.agentic.evals.judge import Judge

    judge = Judge()
    result = judge.score(replay_result)
    print(result["verdict"])     # "fixed" | "still_broken" | "regressed"
    print(result["reasoning"])   # explanation
"""

import json
import logging
import os
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Ensure llm-app root is on the path
_LLM_APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _LLM_APP_ROOT not in sys.path:
    sys.path.insert(0, _LLM_APP_ROOT)


def _build_judge_prompt(replay_result: dict) -> str:
    """Build the judge prompt from a replay result.

    The prompt gives the judge:
    - The original (bad) response
    - The human's feedback (what was wrong)
    - The new response (from current agent)
    - Context (mode, module, student message)
    """
    meta = replay_result.get("meta", {})
    flag_comment = replay_result.get("flag_comment", "")
    original_response = replay_result.get("original_response", "")
    new_response = replay_result.get("new_response", "")

    # Original message is embedded in the meta or we extract from context
    original_message = meta.get("original_message", "")

    return f"""You are evaluating whether a tutor AI agent has improved its behavior after receiving feedback.

## Context
- Mode: {meta.get('mode', 'unknown')}
- Module: {meta.get('module', 'unknown')}
- Agent: {meta.get('agent_type', 'unknown')}

## Original Response (the one that was flagged as problematic)
{original_response}

## Human Feedback (what was wrong with the original response)
{flag_comment}

## New Response (from the current agent, given the IDENTICAL input and context)
{new_response}

## Your Task
Evaluate whether the NEW response addresses the feedback. Consider:
1. Does the new response avoid the mistake described in the feedback?
2. Is the new response better overall, or did it regress in other ways?
3. How confident are you in your assessment?

Respond with ONLY a JSON object in this exact format:
{{
  "verdict": "fixed" | "still_broken" | "regressed",
  "reasoning": "<2-3 sentences explaining your assessment>",
  "confidence": <0.0 to 1.0>,
  "details": {{
    "addresses_feedback": true | false,
    "quality_vs_original": "better" | "same" | "worse",
    "specific_improvement": "<what specifically improved, if anything>"
  }}
}}

Definitions:
- **fixed**: The new response clearly addresses the feedback and is better.
- **still_broken**: The new response still has the same problem described in the feedback.
- **regressed**: The new response is worse than the original in a different way."""


class Judge:
    """Comment-driven LLM Judge for evaluating agent improvements.

    Uses Azure OpenAI to compare original vs new responses against
    human feedback.
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.environ.get(
            "JUDGE_MODEL", "gpt-4o-mini"
        )
        self._model = None

    def _get_model(self):
        """Lazy-init the judge LLM."""
        if self._model is None:
            api_key = os.environ.get("AZURE_OPENAI_API_KEY")
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
            api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

            if api_key and endpoint:
                from langchain_openai import AzureChatOpenAI
                self._model = AzureChatOpenAI(
                    azure_deployment=self.model_name,
                    api_version=api_version,
                    azure_endpoint=endpoint,
                    api_key=api_key,
                    temperature=0.1,
                    max_tokens=1024,
                )
                logger.info(f"[Judge] Using Azure OpenAI: {self.model_name}")
            else:
                # Fallback: try app config
                try:
                    from app.tutor.core.config import get_tutor_model
                    self._model = get_tutor_model()
                    logger.info("[Judge] Using app's configured model")
                except Exception as e:
                    raise RuntimeError(
                        f"No LLM credentials found for judge. "
                        f"Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT. Error: {e}"
                    )
        return self._model

    def score(self, replay_result: dict) -> dict[str, Any]:
        """Score a replayed trace — did the agent fix the flagged issue?

        Args:
            replay_result: Dict from replay_runner.replay_trace() with:
                - original_response, new_response, flag_comment, meta

        Returns:
            Dict with verdict, reasoning, confidence, details.
        """
        # Skip if replay had an error
        new_response = replay_result.get("new_response", "")
        if new_response.startswith("[ERROR]"):
            return {
                "verdict": "error",
                "reasoning": new_response,
                "confidence": 0.0,
                "details": {},
            }

        prompt = _build_judge_prompt(replay_result)
        model = self._get_model()

        try:
            response = model.invoke(prompt)
            text = response.content.strip()

            # Extract JSON (handle markdown code blocks)
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            result = json.loads(text)

            # Ensure required fields
            result.setdefault("verdict", "still_broken")
            result.setdefault("reasoning", "")
            result.setdefault("confidence", 0.5)
            result.setdefault("details", {})

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Judge returned invalid JSON: {e}")
            return {
                "verdict": "error",
                "reasoning": f"Parse error: {e}",
                "confidence": 0.0,
                "details": {},
                "raw_response": text if "text" in dir() else "",
            }
        except Exception as e:
            logger.error(f"Judge scoring failed: {e}")
            return {
                "verdict": "error",
                "reasoning": f"Error: {e}",
                "confidence": 0.0,
                "details": {},
            }
