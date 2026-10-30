# 59 项 PostgreSQL 实际运行结果

开始时间：2026-10-29 01:37:29 ACDT。数据来自本轮 JUnit 和实际选择清单，非源码推算。

| # | 用例 | 状态 | 耗时（秒） |
| --- | --- | --- | --- |
| 1 | `tests/test_retrieval_postgres.py::test_embedding_round_trip` | PASSED | 0.062 |
| 2 | `tests/test_retrieval_postgres.py::test_vector_dimension_enforced` | PASSED | 0.039 |
| 3 | `tests/test_retrieval_postgres.py::test_embedding_pair_constraint[vector0-None]` | PASSED | 0.039 |
| 4 | `tests/test_retrieval_postgres.py::test_embedding_pair_constraint[None-openai:text-embedding-3-small:1536:v1]` | PASSED | 0.037 |
| 5 | `tests/test_retrieval_postgres.py::test_unembedded_chunk_is_preserved` | PASSED | 0.041 |
| 6 | `tests/test_retrieval_postgres.py::test_generation_attempts_serialize` | PASSED | 0.056 |
| 7 | `tests/test_retrieval_postgres.py::test_generation_serializes_with_pdf_refresh[False]` | PASSED | 0.057 |
| 8 | `tests/test_retrieval_postgres.py::test_generation_serializes_with_pdf_refresh[True]` | PASSED | 0.072 |
| 9 | `tests/test_retrieval_postgres.py::test_semantic_ranking_top_k_and_course_isolation` | PASSED | 0.055 |
| 10 | `tests/test_retrieval_postgres.py::test_shared_content_has_course_local_document_metadata` | PASSED | 0.061 |
| 11 | `tests/test_retrieval_postgres.py::test_duplicate_documents_do_not_duplicate_chunks` | PASSED | 0.053 |
| 12 | `tests/test_retrieval_postgres.py::test_ineligible_chunks_are_excluded[unembedded]` | PASSED | 0.063 |
| 13 | `tests/test_retrieval_postgres.py::test_ineligible_chunks_are_excluded[nonready]` | PASSED | 0.057 |
| 14 | `tests/test_retrieval_postgres.py::test_ineligible_chunks_are_excluded[configuration]` | PASSED | 0.064 |
| 15 | `tests/test_retrieval_postgres.py::test_missing_course_does_not_embed` | PASSED | 0.032 |
| 16 | `tests/test_retrieval_postgres.py::test_retrieval_preserves_caller_session_state` | PASSED | 0.064 |
| 17 | `tests/test_retrieval_postgres.py::test_query_and_candidates_share_captured_configuration` | PASSED | 0.054 |
| 18 | `tests/test_retrieval_postgres.py::test_internal_search_validates_inputs[ -5]` | PASSED | 0.036 |
| 19 | `tests/test_retrieval_postgres.py::test_internal_search_validates_inputs[query=2001字符, k=5；完整ID见selection.json]` | PASSED | 0.029 |
| 20 | `tests/test_retrieval_postgres.py::test_internal_search_validates_inputs[valid-0]` | PASSED | 0.024 |
| 21 | `tests/test_retrieval_postgres.py::test_internal_search_validates_inputs[valid-51]` | PASSED | 0.021 |
| 22 | `tests/test_retrieval_postgres.py::test_internal_search_validates_inputs[valid-True]` | PASSED | 0.026 |
| 23 | `tests/test_embedding_backfill.py::test_generation_persists_and_retry_skips_provider[postgres_factory]` | PASSED | 0.045 |
| 24 | `tests/test_embedding_backfill.py::test_force_and_configuration_change_replace_vectors[postgres_factory-True-v1]` | PASSED | 0.087 |
| 25 | `tests/test_embedding_backfill.py::test_force_and_configuration_change_replace_vectors[postgres_factory-False-v2]` | PASSED | 0.053 |
| 26 | `tests/test_embedding_backfill.py::test_later_provider_failure_preserves_all_existing_data[postgres_factory]` | PASSED | 0.039 |
| 27 | `tests/test_embedding_backfill.py::test_invalid_vector_preserves_chunks[postgres_factory]` | PASSED | 0.037 |
| 28 | `tests/test_embedding_backfill.py::test_nonready_content_is_not_mutated[postgres_factory-uploaded]` | PASSED | 0.030 |
| 29 | `tests/test_embedding_backfill.py::test_nonready_content_is_not_mutated[postgres_factory-processing]` | PASSED | 0.044 |
| 30 | `tests/test_embedding_backfill.py::test_nonready_content_is_not_mutated[postgres_factory-failed]` | PASSED | 0.036 |
| 31 | `tests/test_embedding_backfill.py::test_nonready_content_is_not_mutated[postgres_factory-pending_cleanup]` | PASSED | 0.039 |
| 32 | `tests/test_embedding_backfill.py::test_missing_content[postgres_factory]` | PASSED | 0.029 |
| 33 | `tests/test_embedding_backfill.py::test_generation_does_not_commit_pending_writes[postgres_factory]` | PASSED | 0.037 |
| 34 | `tests/test_embedding_backfill.py::test_generation_rejects_caller_savepoint[postgres_factory]` | PASSED | 0.026 |
| 35 | `tests/test_embedding_backfill.py::test_commit_failure_does_not_perform_second_cleanup[postgres_factory]` | PASSED | 0.093 |
| 36 | `tests/test_embedding_backfill.py::test_flush_failure_preserves_embeddings[postgres_factory]` | PASSED | 0.043 |
| 37 | `tests/test_embedding_backfill.py::test_generation_captures_one_configuration[postgres_factory]` | PASSED | 0.037 |
| 38 | `tests/test_embedding_backfill.py::test_cli_reports_failure_but_keeps_completed_content[postgres_factory]` | PASSED | 0.035 |
| 39 | `tests/test_embedding_backfill.py::test_cli_selected_content_is_idempotent[postgres_factory]` | PASSED | 0.041 |
| 40 | `tests/test_embedding_backfill.py::test_generation_normalizes_extreme_provider_output[postgres_factory]` | PASSED | 0.039 |
| 41 | `tests/test_retrieval_api.py::test_search_response_uses_actual_pgvector` | PASSED | 0.056 |
| 42 | `tests/test_retrieval_api.py::test_configurable_default_top_k_and_query_trim` | PASSED | 0.058 |
| 43 | `tests/test_retrieval_api.py::test_provider_failure_returns_safe_503` | PASSED | 0.052 |
| 44 | `tests/test_retrieval_api.py::test_extreme_existing_and_query_vectors_have_correct_serializable_scores[1e+30]` | PASSED | 0.056 |
| 45 | `tests/test_retrieval_api.py::test_extreme_existing_and_query_vectors_have_correct_serializable_scores[1e-40]` | PASSED | 0.056 |
| 46 | `tests/test_processing_postgres.py::test_postgres_waiting_failed_attempt_preserves_winner` | PASSED | 0.063 |
| 47 | `tests/test_processing_postgres.py::test_postgres_replacement_failure_preserves_old_chunks` | PASSED | 0.039 |
| 48 | `tests/test_processing_postgres.py::test_postgres_successful_refresh_is_canonical` | PASSED | 0.038 |
| 49 | `tests/test_processing_postgres.py::test_postgres_constraint_failure_rolls_back_replacement` | PASSED | 0.047 |
| 50 | `tests/test_retrieval_migrations.py::test_upgrade_existing_head_preserves_chunks_and_round_trips` | PASSED | 2.422 |
| 51 | `tests/test_retrieval_eval.py::test_deterministic_topic_evaluation` | PASSED | 0.063 |
| 52 | `tests/test_retrieval_eval.py::test_evaluation_cli_cleans_schema_and_preserves_existing_courses[False]` | PASSED | 0.094 |
| 53 | `tests/test_retrieval_eval.py::test_evaluation_cli_cleans_schema_and_preserves_existing_courses[True]` | PASSED | 0.069 |
| 54 | `tests/test_retrieval_eval.py::test_topic_tie_does_not_count_as_semantic_success` | PASSED | 0.095 |
| 55 | `tests/test_course_retrieval_eval.py::test_real_pgvector_benchmark_measures_full_rank_and_keeps_evidence` | PASSED | 0.070 |
| 56 | `tests/test_course_retrieval_eval.py::test_benchmark_cli_cleans_schema_on_success_and_provider_failure[False]` | PASSED | 0.111 |
| 57 | `tests/test_course_retrieval_eval.py::test_benchmark_cli_cleans_schema_on_success_and_provider_failure[True]` | PASSED | 0.070 |
| 58 | `tests/test_course_retrieval_eval.py::test_answer_bearing_alternative_counts_as_relevant_before_live_measurement[H02-02-shared-memory-notes.txt]` | PASSED | 0.129 |
| 59 | `tests/test_course_retrieval_eval.py::test_answer_bearing_alternative_counts_as_relevant_before_live_measurement[H03-03-message-passing-notes.txt]` | PASSED | 0.113 |
