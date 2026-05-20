export VLLM_PROVIDER_ID=vllm-small
export VLLM_MODEL_ID=hosted_vllm/chat:latest

export OATS_ENABLED=0

# disabled with 0, enabled with anything else
export CODER_DISABLED_CLOUD_MODELS=0

export CODER_CTX_LEN=8000
# export CODER_CHAT_URL=http://open-webui-host:port
export CODER_CHAT_URL=
export CODER_CHAT_PASSWORD=
export CODER_CHAT_EMAIL=
export CODER_NAME=
# local s3 with a tasks1 bucket
CODER_S3_BUCKET=tasks1
# export CODER_CONFIG_FILE=/opt/ds/coder.json
export CODER_CONFIG_FILE=
# export CODER_TOOL_USES_INDEX=/opt/ds/oats/.ai/AGENT.repo_uses.python.tools.json
export CODER_TOOL_USES_INDEX=.ai/AGENT.repo_uses.python.tools.json

# Coder - Tool - MCP Feature Flags
export CODER_PROFILE=full
export CODER_TOOL_USES_INDEX=
export CODER_TOOLS_API_KEY=
# export CODER_TOOL_BASE_DIR=/opt/ds/oats
export CODER_TOOL_BASE_DIR=

# OR custom feature flags
# export CODER_FEATURE_WEB_TOOLS=1
# export CODER_FEATURE_PLANNING=1
# export CODER_FEATURE_MEMORY=1
# export CODER_FEATURE_AGENTS=1
# export CODER_FEATURE_CERTIFICATES=1
# export CODER_FEATURE_LSP=1
# export CODER_FEATURE_MCP=1

# disable litellm token price downloading on startup
export LITELLM_LOCAL_MODEL_COST_MAP=True

export COLORS_ENABLED=1
export ENV_NAME=prod

export TOOL_API_URL=http://0.0.0.0:20700/v1
export TOOL_API_KEY=CHANGE_PASSWORD

export VLLM_PROVIDER_ID=vllm-small
export VLLM_MODEL_ID=hosted_vllm/chat:latest

export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
