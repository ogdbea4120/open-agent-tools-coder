# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "open-agent-tools-coder"
copyright = "2026, District Solutions"
author = "District Solutions"
release = "1.0.12"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx_autodoc_typehints",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
    "sphinx.ext.githubpages",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Napoleon settings -------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True

# -- Autodoc settings --------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "signature"
autodoc_typehints_format = "short"

# -- Type aliases for forward references ------------------------------------
autodoc_type_aliases = {
    "JsonValue": "JsonValue",
    # "HookContext": "HookContext",
}

# -- Nitpick: ignore types we can't resolve ----------------------------------
nitpick_ignore = [
    ("py:class", "JsonValue"),
    # ("py:class", "HookContext"),
    # ("py:class", "HookResult"),
    ("py:class", "type"),
]

# -- sphinx_autodoc_typehints settings --------------------------------------
# Suppress warnings for pydantic internal types that can't be resolved
always_document_param_types = False

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_logo = ""
html_favicon = ""
