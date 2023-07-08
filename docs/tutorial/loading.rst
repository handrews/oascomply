Loading APIDs and Schemas
=========================

To use ``oascomply`` on an APID, you need to tell it how to load
the documents that make up the APID, and how to resolve references
among those documents.  This is automatic if your APID consists of just
one self-contained document.  For more multi-document APIDs, ``oascomply``
needs to know how *URIs* in references (``"$ref"``) map to the local file
or network resource *URLs*

* See :doc:`overview` for definitions of **APID** and **document**.
* See :doc:`url-uri-iri` for background on when and why it is important
    to distinguish aong **URLs**, **URIs**, and/or **IRIs**, as well as
    the distinction between these terms and **relative references** and
    other terminology

Use cases
---------

``oascomply``'s command-line options are designed to make the following
real-world development and deployment use cases as easy as possible:

* single-document APIDs that use only same-document references (``"$ref": "#/components/schemas/foo"``)
* multi-document APIDs that exist in only one environment (no separate dev/test/production deployments)
* multi-document APIDs with multiple deployment environments (dev vs test vs prod or otherwise)...
    * using portable relative references (``"$ref": "foo/bar"``) that work in all deployments
    * developed using file extension suffixes (``foo/bar.json``) but referenced without (``"$ref": "foo/bar"``)
    * environments using different prefixes that impact references (local ``~/src/foo/bar`` with ``"$ref: "https://example.com/foo/bar"``)
    * environments using both different prefixes *and* local file extension suffixes that are not present in references

``oascomply`` can also support complex mixtures of the above scenarios,
including arbitrary differences between development and production environments,
although the most complex cases require complex command-line arguments.

These use cases are handled by mapping each document's ***URL***
(the location from which it is loaded) to its ***URI*** (the way it
is identified in references).

See :doc:`url-uri-iri` for how ``oascomply`` defines *URL* and *URI*, and why
it uses those terms in this way, as well as other related topics.


Command-line summary
--------------------

The following tables summarize the command-line options used to configure
``oascompy`` document loading and reference resolution.  FILE and DIR arguments
are converted to the equivalent ``file:`` URLs within the code and in most output
so that they can be treated consistently with ``http(s):`` URLs.

Since compliex APIDs can require long command lines, the ``@`` prefix can be used to
`load options from a file <https://docs.python.org/3.8/library/argparse.html#fromfile-prefix-chars>`_

**Options for loading individual documents:**

====== ====================== ================================= ==================================== ====================
short  long                   args                              behavior                             default
====== ====================== ================================= ==================================== ====================
``-i`` ``--initial-document`` (``FILE`` | ``URL``) [``URI``]    *see* ***initial document*** *table*
``-f`` ``--file``             ``FILE`` [``URI``] [``TYPE``]     map URI to FILE
``-u`` ``--url``              ``URL`` [``URI``] [``TYPE``]      map URI to URL
``-x`` ``--strip-suffixes``   ``SUFFIX`` [``SUFFIX`` ...]       strip any suffixes present           ``.json .yaml .yml``
====== ====================== ================================= ==================================== ====================

* ``-f`` and ``-u`` can be repeated as many times as necessary
* ``-x`` can only be specified once and applies to all ``-f`` and ``-u`` without the ``URI`` argument
* When ``URI`` is omitted, the ``URL`` (``-u``) or the ``file:`` URL
    corresponding to ``FILE`` (``-f``) is used, as modified based on ``-x``
* ``-x`` is **ignored** for ``-f`` and ``-u`` options that have a ``URI`` argument

**Options for resolving references from sets of possible documents:**

====== =================== ================================= =================================== =======================
short  long                args                              behavior                            default
====== =================== ================================= =================================== =======================
``-d`` ``--directory``       ``DIR`` [``URI_PREFIX``]        replace URI_PREFIX with DIR
``-p`` ``--url-prefix``      ``URL_PREFIX`` [``URI_PREFIX``] replace URI_PREFIX with URL_PREFIX
``-F`` ``--file-suffixes``   ``SUFFIX`` [``SUFFIX`` ...]     try each path suffix in order       ``.json .yaml .yml``
``-U`` ``--url-suffixes``    ``SUFFIX`` [``SUFFIX`` ...]     try each URL suffix in order        ``"" .json .yaml .yml``
====== =================== ================================= =================================== =======================

**Managing options:**

* ``-f``, ``-d``, ``-u``, and ``-p`` can be repeated as many times as necessary

**URL and URI schemes:**

* Only ``http:`` and ``https:`` URLs and URL prefixes are supported for ``-u`` and ``-p``
* URIs and URI prefixes can use any scheme, including non-URL schemes like ``urn:``
* All URL and URI prefixes **must** have a path component ending in  ``/``,
    which aligns URL/URI_PREFIX behavior with DIR behavior

**File extension suffixes:**
* ``-x`` unconditionally strips one suffix (e.g. ``.json`` or ``.whatever``)
* ``SUFFIX`` **must** include the leading dot (e.g. ``.json``) or **may** be the empty string (quoted appropriately for your shell, e.g. ``""``)
* Complex mappings that aren't handled by ``-x``, ``-d``, ``-p``, ``-F``, and ``-U`` can be supported by mapping each document individually with ``-f`` and ``-u``

The ``-i`` option tells ``oascomply`` where to start processing the APID:

============== ========================= ================================ =========================
``-i``         ``-d``                    ``-p``                           effect
============== ========================= ================================ =========================
``FILE [URI]``                                                            same as ``-f FILE [URI]``
``URL [URI]``                                                             same as ``-u URL [URI``
``FILE``       ``DIR`` contains ``FILE``                                  maps URI based on ``-d``
``URL``                                  ``URL_PREFIX`` prefix of ``URL`` maps URI based on ``-p``
``FILE  URI``  ``DIR`` contains ``FILE``                                  same as ``-f FILE [URI]``
``URL  URL``                             ``URL_PREFIX`` prefix of ``URL`` same as ``-u URL [URI``
============== ========================= ================================ =========================


If it is absent, ``oascomply`` looks for a document containing an ``openapi`` field, first in the ``-f`` options in the order they were passed, then the ``-u`` options.


When optional URI or URI_PREFIX options are omitted, the URL or URL prefix is used in
its place.  Local FILE and DIR values are converted to ``file:`` URIs, potentially with
any file extension removed depending on the value of ``-x``.

Note that:

* All URLs and URL prefixes **must** be ``http:`` or preferably ``https:``

Single-document APIDs
---------------------



References, identity, and location
----------------------------------

Let's assume your APID consists of two documents:

* the main OAS document, called ``openapi``
* a separate JSON Schema, called ``bigschema``

Let's assume that you deploy your API to production at the following URLs,
which can serve the as the media types listed for each:

* ``https://example.com/apid/openapi``
    * ``application/openapi+json`` (default)
    * ``application/json``
    * ``application/openapi+yaml``
    * ``application/yaml`` (`finally almost a standard! <https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-yaml-mediatypes-09>`_)
* ``https://example.com/apid/schemas/bigschema``
    * ``application/schema+json`` (default, `maybe a standard one day... <https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-rest-api-mediatypes-03>`_)
    * ``application/json``

An HTTP GET on either without an ``Accept`` header will come back with
a ``Content-Type`` header of ``application/openapi+json`` for ``openapi``,
and ``application/schema+json`` for ``bigschema``.


the main OAS document
(containing the ``openapi`` field in its root object) and a large schema

References (``"$ref"``) in multi-document APIDs are often written for the
production deployment location, while tools like ``oascomply`` are often
run in development or testing environments.

In some cases, careful use of relative URL references in ``"$ref"``
If you are running ``oascomply`` in a development or testing environment
where the APID documents must be loaded from a location other than the
production deployment, kkkkk
References are usually written for the APID's deployed state, typically
HTTPS resources without file extensions (with the format determined by
HTTP content negotiation).  The URI references in such ``"$ref"`` values
*identify* the reference target based on its production location.

Tools like ``oascomply`` are often run in develoment environments where
APID documents are local files, with the format indicated by file
extensions such as ``.json`` to support syntax highlighting and other tools.
Loading the correct documents requires kkkkk
Problems with reference resolution are often the result of misconfigured
URL-URI mapping.
While many OAS documents are completely self-contained, it is also
possible to work with multipel

APIDs and "documents"
+++++++++++++++++++++

If you ask an OpenAPI Specification (OAS) user what they call the set
of OAS-compliant files and/or network resources associated with an API,
you will likely get any one of *"API definition"*, *"API description"*,
or *"API document"*.  Some will use "API document" even if that "document"
consists of multiple files and/or network resources.

Within ``oascomply``, a "document" is always a ***single*** OAS-compliant
local file or network resource.  The complete set of one or more such
documents associated with an API is always called an ***APID***, where
the exact meaning of the "D" is left unspecified.


Since there is no consensus within the OpenAPI community on the correct
term for a set of
***Note:** There is much debate in the OpenAPI community as to whether
the OpenAPI Specification (OAS) is used to **define** or **describe**
an API.  Some OAS users sidestep this by referring to an API's
**OAS document**, even if that "document" consists of multiple files
or network resources.

APIDs (API definitions/descriptions/documents) consist of one or more
local files or network resources.  These can be loaded by the ``oascomply``
command-line utility, which parses them into the sort of data structure
produced by the Python standard ``json`` library.  When using ``oascomply``
as a library, application code can also pass such data structures
directly.


