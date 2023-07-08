.. oascomply documentation master file, created by
   sphinx-quickstart on Thu Jun 22 16:00:02 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to oascomply!
=====================

``oascomply`` is an extensible library and command-line tool for parsing,
validating, and linting API Definitions/Descriptions/Documents (**APIDs**)
that are compliant with the OpenAPI Specification (**OAS**).

To parse and validate an APID that consists of a single local file named
``openapi.json``, use the following command line:

.. code:: console

   user@host % oascomply -f openapi.json

For more complex scenarios and features, see the :doc:`tutorial`.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   tutorial
   contributing
   modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
