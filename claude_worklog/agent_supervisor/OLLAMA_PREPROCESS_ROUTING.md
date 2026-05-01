# Ollama Preprocess Routing for Split Task 012

Purpose: generate short context digests to reduce Claude token usage before running split remediation tasks.

## Output directory

- `claude_worklog/agent_supervisor/ollama_context/`

## Run order

1. `011o_summarize_codex_blockers`
2. `012ao_summarize_database_schema_context`
3. `012bo_summarize_api_contract_context`
4. `012co_summarize_feature_explainability_context`
5. `012do_summarize_trainer_liveness_context`

## Commands

- `python3 claude_worklog/tools/agent_supervisor.py --task-id 011o_summarize_codex_blockers`
- `python3 claude_worklog/tools/agent_supervisor.py --task-id 012ao_summarize_database_schema_context`
- `python3 claude_worklog/tools/agent_supervisor.py --task-id 012bo_summarize_api_contract_context`
- `python3 claude_worklog/tools/agent_supervisor.py --task-id 012co_summarize_feature_explainability_context`
- `python3 claude_worklog/tools/agent_supervisor.py --task-id 012do_summarize_trainer_liveness_context`

## Routing into Claude tasks

- `012a_database_lineage_constraints` reads `ollama_context/012a_database_schema_context.md` if present.
- `012b_api_lineage_enforcement` reads `ollama_context/012b_api_contract_context.md` if present.
- `012c_feature_explainability_completeness` reads `ollama_context/012c_feature_explainability_context.md` if present.
- `012d_trainer_liveness_validation_evidence` reads `ollama_context/012d_trainer_liveness_context.md` if present.
- `012e_milestone_go_no_go_integration` reads `ollama_context/011o_codex_blockers_summary.md` if present.

Do not run Claude split tasks until preprocessing context files are available and Claude quota is ready.
