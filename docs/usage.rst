Usage
=====

Interactive Mode
----------------

Launch the interactive REPL:

.. code-block:: bash

   oat

Resume the last session:

.. code-block:: bash

   oat -r last

Specify a model:

.. code-block:: bash

   oat -m hosted_vllm/Qwen3-32B-AWQ

Slash Commands
--------------

By default, prompts without a leading ``/`` are treated as chat messages.
The following internal slash commands are supported:

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Command
     - Description
   * - ``/help``
     - Show supported usage information
   * - ``/mode``
     - Change the operating mode
   * - ``/approve``
     - Toggle auto-approval mode
   * - ``/browse``
     - Browse a URL using Playwright; store as JSON/Parquet on S3
   * - ``/clear``
     - Clear the current session
   * - ``/session``
     - View the current session details
   * - ``/cost``
     - View token usage and cost
   * - ``/config``
     - View the current configuration
   * - ``/profile``
     - View coder profile feature flags
   * - ``/files``
     - View the current files
   * - ``/diff``
     - View the git diff for the repo
   * - ``/log``
     - View the logs
   * - ``/history``
     - View the chat history
   * - ``/tools``
     - View the default tools
   * - ``/model``
     - View the current provider model
   * - ``/models``
     - View available models
   * - ``/new``
     - Start a new session
   * - ``/switch``
     - Switch provider
   * - ``/provider``
     - View the current provider
   * - ``/compact``
     - Manually compact the chat session

Configuration
-------------

Set the configuration file via environment variable:

.. code-block:: bash

   export CODER_CONFIG_FILE=./oats/config/coder.json

Check provider status:

.. code-block:: bash

   pv

Troubleshooting
---------------

**vLLM Unauthorized Error**

If you see:

.. code-block:: text

   LLM error: litellm.AuthenticationError: AuthenticationError: Hosted_vllmException - {"error":"Unauthorized"}

Ensure your ``CODER_CONFIG_FILE`` environment variable points to the correct
configuration file. Then run ``pv`` to confirm providers are configured.
