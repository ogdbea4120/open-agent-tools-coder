.. oats-coder documentation master file, created by sphinx-quickstart.

Welcome to Open Agent Tools Coder Documentation
===============================================

**Open Agent Tools (oats)** enables small-to-large self-hosted AI models to use
local source code when running tool-calling agentic workloads. We actively data
mine 20,970+ (2+ TB) popular GitHub repos using large and small AI models to
create reusable JSON, Markdown, and Parquet files for local-first tool-calling
models.

Over multiple passes, we compile and export a fast, compressed prompt index for
all Python source code in any repo. Agents refer to the local prompt index to
use already-written source code on disk instead of HTTP with MCP or having an
expensive frontier AI model re-build something that is already working locally
with expensive tokens.

Key Features
------------

- Run local self-hosted models that can execute 1–250+ local tool-calling
  commands using an agentic coding AI.
- Supports over **141,000 tools** using the `open-agent-tools prompt indices
  repo <https://github.com/district-solutions/open-agent-tools>`_.
- Find more OATs Prompt Indices Datasets on
  `HuggingFace <https://huggingface.co/datasets/open-agent-tools/open-tools>`_.

Quick Start
-----------

.. code-block:: bash

   git clone https://github.com/district-solutions/open-agent-tools-coder oats
   cd oats
   pip install -e .
   pip install --upgrade aiohttp

Then launch the interactive coder:

.. code-block:: bash

   oat

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   usage

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/index

.. toctree::
   :maxdepth: 1
   :caption: Project

   changelog

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
