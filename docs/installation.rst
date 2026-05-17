Installation
============

Prerequisites
-------------

- Python 3.10 or later
- pip (or your preferred Python package manager)

Install from Source
-------------------

.. code-block:: bash

   git clone https://github.com/district-solutions/open-agent-tools-coder oats
   cd oats
   pip install -e .

After installation, upgrade ``aiohttp`` (litellm installs an older version):

.. code-block:: bash

   pip install --upgrade aiohttp

Optional Dependencies
---------------------

**Browser tools (Playwright):**

.. code-block:: bash

   pip install -e ".[browser]"

**Development tools:**

.. code-block:: bash

   pip install -e ".[dev]"

**Documentation build tools:**

.. code-block:: bash

   pip install -e ".[docs]"

Verify Installation
-------------------

Run the environment validation command:

.. code-block:: bash

   check-coder-env

Or validate prompt-to-tool mapping:

.. code-block:: bash

   get-tools -p 'get third friday'

This should return a valid JSON dictionary with tool choices.

Command-Line Entry Points
-------------------------

After installation, the following commands are available:

- ``oat`` / ``ff`` — Launch the interactive coder REPL
- ``get-tools`` — Query which tools match a given prompt
- ``pv`` — Check provider configuration status
- ``check-coder-env`` — Validate the coder environment
- ``setup-coder`` — Set up the coder configuration
