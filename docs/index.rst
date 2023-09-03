Welcome to OASComply
====================

Testing for compliance with the OpenAPI Specification (**OAS**) has always been a challenge,
leading to two unmet needs in the OpenAPI community:

* `OpenAPI Description <https://learn.openapis.org/>`_ (**OAD**) authors want to know whether their OAD is correctly written
* OAS tool developers want to know whether their tool parses and interprets OADs correctly

The OAS defines a format for *describing* an API's interface and behavior.  Unlike most specifications,
it does not define measurable output, and the output produced by OpenAPI tools varies tremendously in form and purpose.

The only thing all OAS-based tools have in common is that they *interpret* OADs and *express* that
interpretation in some way.  This is where we can test for compliance:

.. important::

    An OpenAPI tool is compliant with the OpenAPI Specification if it expresses the same **meaning**
    that the OAS defines for a given OAD.

Since the expression varies so much, we can only test the *interpretation* of the OAD's meaning.

The OASComply project defines a *machine-readable encoding* of the *interpretation* of an OAD.  This encoding can be sorted and
diff'd, loaded into any `graph database <https://en.wikipedia.org/wiki/Graph_database>`_ for analysis or visualization,
or used as pre-parsed input to an OpenAPI-related tool.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   quickstart
   guide/index
   modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
