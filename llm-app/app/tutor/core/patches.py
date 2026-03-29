"""Startup patches — workarounds for library bugs.

Import this module once at application startup (e.g. in app/tutor/__init__.py)
to apply all necessary patches.

Patches:
1. SkillsMiddleware forced reload — prevents stale skills_metadata=[] from
   checkpointed state blocking skill discovery.
2. HttpResponse.json property fix — prevents crashes during streaming API errors
   when langchain_core checks hasattr(response, 'json').
"""

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Patch 1: Force SkillsMiddleware to reload skills every invocation
# ═══════════════════════════════════════════════════════════════════════════════
# The middleware skips loading if skills_metadata is already in state.
# With checkpointing, a stale empty [] gets persisted and skills are never
# discovered again. This patch forces a reload every invocation.

from deepagents.middleware.skills import SkillsMiddleware, _alist_skills, SkillsStateUpdate

_orig_abefore = SkillsMiddleware.abefore_agent


async def _forced_abefore(self, state, runtime, config):
    """Always reload skills, ignoring cached skills_metadata in state."""
    backend = self._get_backend(state, runtime, config)
    all_skills = {}

    for source_path in self.sources:
        try:
            source_skills = await _alist_skills(backend, source_path)
            for skill in source_skills:
                all_skills[skill["name"]] = skill
        except Exception as e:
            logger.warning("[SkillsMW] Error loading skills from %s: %s", source_path, e)

    skills = list(all_skills.values())
    logger.info("[SkillsMW] Loaded %d skills: %s", len(skills), [s.get("name") for s in skills])
    return SkillsStateUpdate(skills_metadata=skills)


SkillsMiddleware.abefore_agent = _forced_abefore
logger.info("[SkillsMW] Force-reload patch applied")


# ═══════════════════════════════════════════════════════════════════════════════
# Patch 3: LangSmith Skill Trace Visibility
# ═══════════════════════════════════════════════════════════════════════════════
# Intercepts the model call to emit a named LangSmith span showing which
# skills are currently active based on the LLM's read_file history.

import langsmith

_orig_awrap = SkillsMiddleware.awrap_model_call

async def _traced_awrap(self, request, handler):
    modified_request = self.modify_request(request)
    
    active_skills = set()
    messages = request.state.get("messages", [])
    skills_meta = request.state.get("skills_metadata", [])
    skill_paths = {s["path"]: s["name"] for s in skills_meta}
    
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("name") == "read_file":
                    args = tc.get("args", {})
                    path = args.get("file_path", "") if isinstance(args, dict) else ""
                    if path in skill_paths:
                        active_skills.add(skill_paths[path])
                        
    span_name = f"Active Skills: {', '.join(sorted(active_skills))}" if active_skills else "Active Skills: Assessing Needs"
    
    @langsmith.traceable(name=span_name, run_type="chain")
    async def _run_model_with_trace():
        return await handler(modified_request)
        
    return await _run_model_with_trace()

SkillsMiddleware.awrap_model_call = _traced_awrap
logger.info("[SkillsMW] LangSmith trace visibility patch applied")


# ═══════════════════════════════════════════════════════════════════════════════
# Patch 2: Fix google.genai HttpResponse.json property crash
# ═══════════════════════════════════════════════════════════════════════════════
# langchain_core assumes .json is a method and calls hasattr(response, "json").
# google.genai implements .json as a property that fails when the response is
# a single httpx.Response object (as happens during streaming API errors).

try:
    from google.genai._api_client import HttpResponse
    import httpx

    def _json_patch(self):
        if isinstance(self.response_stream, list):
            if not self.response_stream or not self.response_stream[0]:
                return ''
            return self._load_json_from_response(self.response_stream[0])

        if isinstance(self.response_stream, httpx.Response):
            try:
                return self.response_stream.json()
            except Exception:
                return ''

        if hasattr(self.response_stream, '__getitem__') and not isinstance(self.response_stream, httpx.Response):
            if not self.response_stream[0]:
                return ''
            return self._load_json_from_response(self.response_stream[0])

        return ''

    HttpResponse.json = property(_json_patch)
    logger.info("[HttpResponse] json property patch applied")
except ImportError:
    pass
