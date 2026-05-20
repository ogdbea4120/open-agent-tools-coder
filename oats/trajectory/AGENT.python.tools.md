# Agent Python Tools

- repo: oats
- repo_uri: https://github.com/district-solutions/open-agent-tools-coder.git

## File: oats/trajectory/logger.py

Prompts

```
['install the trajectory logger to register global hooks for recording user prompts and tool results', 'reset the trajectory logger state and clear per-session turn counters for testing', 'review the async hook handler that records user prompts into the trajectory store', 'review the async hook handler that records tool results with args and output into the store', 'review the thread-safe turn index generator that backfills from the SQLite trajectory store', 'log retrieval data for a conversation turn including trajectory ids and scores to the metrics store', 'log the outcome of a finished turn with iteration count, tool errors, and completion status', 'aggregate turn metrics from the last N days into a cohort comparison dict for retrieval vs no retrieval', 'format a turn metrics report dict into a Markdown table comparing retrieval cohorts', 'create a TurnMetricRow dataclass instance to represent a single turn metric record with session and turn data', 'retrieve past trajectory examples similar to a user prompt from the trajectory store', 'format a list of retrieved examples into a markdown section for the system prompt', 'format a single retrieval-augmented example into a plain text string with content capping', 'create an Example dataclass instance with a score, prompt record, and continuation records', 'retrieve trajectory examples while excluding the current session to avoid stale results', 'record a trajectory turn with session id, role, kind, and content to the SQLite store', 'async record a trajectory turn to the store without blocking the event loop', 'search past trajectory turns by query text using BM25 ranking and optional filters', 'get all turns for a given session id ordered by turn index from the store', 'get the process-wide trajectory store singleton creating it on first use with an optional db path']
```

Usage

```
{'install_trajectory_logger': 'install the trajectory logger to register global hooks for recording user prompts and tool results', 'reset_for_tests': 'reset the trajectory logger state and clear per-session turn counters for testing', 'review_on_user_prompt': 'review the async hook handler that records user prompts into the trajectory store', 'review_on_tool_result': 'review the async hook handler that records tool results with args and output into the store', 'review_next_turn': 'review the thread-safe turn index generator that backfills from the SQLite trajectory store'}
```

## File: oats/trajectory/metrics.py

Prompts

```
['install the trajectory logger to register global hooks for recording user prompts and tool results', 'reset the trajectory logger state and clear per-session turn counters for testing', 'review the async hook handler that records user prompts into the trajectory store', 'review the async hook handler that records tool results with args and output into the store', 'review the thread-safe turn index generator that backfills from the SQLite trajectory store', 'log retrieval data for a conversation turn including trajectory ids and scores to the metrics store', 'log the outcome of a finished turn with iteration count, tool errors, and completion status', 'aggregate turn metrics from the last N days into a cohort comparison dict for retrieval vs no retrieval', 'format a turn metrics report dict into a Markdown table comparing retrieval cohorts', 'create a TurnMetricRow dataclass instance to represent a single turn metric record with session and turn data', 'retrieve past trajectory examples similar to a user prompt from the trajectory store', 'format a list of retrieved examples into a markdown section for the system prompt', 'format a single retrieval-augmented example into a plain text string with content capping', 'create an Example dataclass instance with a score, prompt record, and continuation records', 'retrieve trajectory examples while excluding the current session to avoid stale results', 'record a trajectory turn with session id, role, kind, and content to the SQLite store', 'async record a trajectory turn to the store without blocking the event loop', 'search past trajectory turns by query text using BM25 ranking and optional filters', 'get all turns for a given session id ordered by turn index from the store', 'get the process-wide trajectory store singleton creating it on first use with an optional db path']
```

Usage

```
{'log_retrieval_used': 'log retrieval data for a conversation turn including trajectory ids and scores to the metrics store', 'log_turn_outcome': 'log the outcome of a finished turn with iteration count, tool errors, and completion status', 'report': 'aggregate turn metrics from the last N days into a cohort comparison dict for retrieval vs no retrieval', 'format_report_markdown': 'format a turn metrics report dict into a Markdown table comparing retrieval cohorts', 'TurnMetricRow': 'create a TurnMetricRow dataclass instance to represent a single turn metric record with session and turn data'}
```

## File: oats/trajectory/retrieval.py

Prompts

```
['install the trajectory logger to register global hooks for recording user prompts and tool results', 'reset the trajectory logger state and clear per-session turn counters for testing', 'review the async hook handler that records user prompts into the trajectory store', 'review the async hook handler that records tool results with args and output into the store', 'review the thread-safe turn index generator that backfills from the SQLite trajectory store', 'log retrieval data for a conversation turn including trajectory ids and scores to the metrics store', 'log the outcome of a finished turn with iteration count, tool errors, and completion status', 'aggregate turn metrics from the last N days into a cohort comparison dict for retrieval vs no retrieval', 'format a turn metrics report dict into a Markdown table comparing retrieval cohorts', 'create a TurnMetricRow dataclass instance to represent a single turn metric record with session and turn data', 'retrieve past trajectory examples similar to a user prompt from the trajectory store', 'format a list of retrieved examples into a markdown section for the system prompt', 'format a single retrieval-augmented example into a plain text string with content capping', 'create an Example dataclass instance with a score, prompt record, and continuation records', 'retrieve trajectory examples while excluding the current session to avoid stale results', 'record a trajectory turn with session id, role, kind, and content to the SQLite store', 'async record a trajectory turn to the store without blocking the event loop', 'search past trajectory turns by query text using BM25 ranking and optional filters', 'get all turns for a given session id ordered by turn index from the store', 'get the process-wide trajectory store singleton creating it on first use with an optional db path']
```

Usage

```
{'retrieve_examples': 'retrieve past trajectory examples similar to a user prompt from the trajectory store', 'format_examples_section': 'format a list of retrieved examples into a markdown section for the system prompt', 'Example_format': 'format a single retrieval-augmented example into a plain text string with content capping', 'Example_class': 'create an Example dataclass instance with a score, prompt record, and continuation records', 'retrieve_examples_exclude_session': 'retrieve trajectory examples while excluding the current session to avoid stale results'}
```

## File: oats/trajectory/store.py

Prompts

```
['install the trajectory logger to register global hooks for recording user prompts and tool results', 'reset the trajectory logger state and clear per-session turn counters for testing', 'review the async hook handler that records user prompts into the trajectory store', 'review the async hook handler that records tool results with args and output into the store', 'review the thread-safe turn index generator that backfills from the SQLite trajectory store', 'log retrieval data for a conversation turn including trajectory ids and scores to the metrics store', 'log the outcome of a finished turn with iteration count, tool errors, and completion status', 'aggregate turn metrics from the last N days into a cohort comparison dict for retrieval vs no retrieval', 'format a turn metrics report dict into a Markdown table comparing retrieval cohorts', 'create a TurnMetricRow dataclass instance to represent a single turn metric record with session and turn data', 'retrieve past trajectory examples similar to a user prompt from the trajectory store', 'format a list of retrieved examples into a markdown section for the system prompt', 'format a single retrieval-augmented example into a plain text string with content capping', 'create an Example dataclass instance with a score, prompt record, and continuation records', 'retrieve trajectory examples while excluding the current session to avoid stale results', 'record a trajectory turn with session id, role, kind, and content to the SQLite store', 'async record a trajectory turn to the store without blocking the event loop', 'search past trajectory turns by query text using BM25 ranking and optional filters', 'get all turns for a given session id ordered by turn index from the store', 'get the process-wide trajectory store singleton creating it on first use with an optional db path']
```

Usage

```
{'record_turn': 'record a trajectory turn with session id, role, kind, and content to the SQLite store', 'arecord_turn_async': 'async record a trajectory turn to the store without blocking the event loop', 'search_turns_bm25': 'search past trajectory turns by query text using BM25 ranking and optional filters', 'get_session_turns': 'get all turns for a given session id ordered by turn index from the store', 'get_trajectory_store': 'get the process-wide trajectory store singleton creating it on first use with an optional db path'}
```

