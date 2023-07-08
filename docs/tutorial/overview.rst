Overview
========

The OpenAPI Specification (**OAS**) is used to document, describe, and/or
define HTTP APIs.  ``oascomply`` is intended to give both users and tooling
vendors confidence that they are making use of OAS's features correctly.

Supported versions and formats
------------------------------

OAS versions:

* 3.0:  Fully supported
* 3.1:  Architecturally supported, to be enabled by end of 2023

Input formats:

* JSON:  Supported, with optional line numbers; fast
* YAML:  Supported, with optional line numbers; slow
* *extensible*, see :doc:`../contributing/extending`

Note that the slowness of YAML is only noticeable on larger documents,
and is inherent in its relative complexity compared to JSON

Output formats:

* N-Triples 1.1: default output
* Other RDF representations: as supported by ``rdflib``

Terminology and Definitions
---------------------------

``oascomply`` uses the following definitions:

* **document**: a local file, network resource, or other form of storing
    and accessing content (in-memory string, database field, etc.)
* **APID**: one or more documents that define/describe an API; since the
    question of "define" vs "describe" vs "document" is hotly debated,
    ``oascomply`` takes no position on the meaning of the "D" in "APID"
* **URL**: a URI or IRI *intended* to be used to locate and interact with
    a resource, in accordance with the rules for its scheme (e.g. ``https:``)
* **IRI**: essentially a URI with unicode support

See :doc:`url-uri-iri` for a more in-depth discussion of resource identifiers
and relative references, including when and why the URL vs URI distinction
is important.

stuff
-----

``oascomply`` is designed to support OAS 3.x, with the intention of being
extensible to OAS 4 and later versions.  As this package is still under
development, only OAS 3.0 is currently supported.  OAS 3.1 support will
be added before the end of 2023 once the code has stabilized, but key aspects
of OAS 3.1 support such as full JSON Schema draft 2020-12 suppport are
already present internally.

Both JSON and YAML are supported, but due to the nature of YAML it is
substantially slower to parse.  For small documents this does not matter,
but if you are running ``oascomply`` repeatedly on a large document,
and particularly if you are enabling line and column number support
in the output, converting your YAML documents to JSON while working with
``oascomply`` will speed things up considerably.

For adding support for formats beyond JSON or YAML,
see :doc:`../contributing/extending`

APID: Document? Define? Describe?
----------------------------------

Opinions within the OpenAPI community vary as to whether one uses the OAS
to *define*, *describe*, or *document* an API, and whether the thing one
creates is an API *definition*, *description*, or *document*.

``oascomply`` avoids this debate by using the acronym **APID** without
specifying what the "D" represents.  However, ``oascomply`` uses the term
*document* for a single local file or network resource that contains all
or part of an APID.

APIDs can be contained within a single document or spread across multiple
documents that are connected by references.  For more on how to work with
multi-document APIDs, see :doc:`loading`.

What does it mean to comply with or support the OAS?
----------------------------------------------------

Most specifications define an input, a way of processing that input, and an
output.  Implementations then test whether they get the expected output from
inputs that exercise the various features of the spec.

In contrast, the OAS specifies how to represent the behavior of an API, and
OAS tools implement a wide range of applications based on that behavior.
Tools might generate code or documentation, or perform some sort of validation
of HTTP messages, or mapping of application data into or out of such messages.
j

The OAS is challenging because it does not specify any sort of output or
behavior

One challenge with implementing and using the OAS is that
it does not define any specific output with which all implementations must
comply.  This is different from other specifications:  HTML defines how a page
should be rendered by a browser.  JSON Schema defines how to produce a
boolean "pass" or "fail" validation outcome and (in more recent drafts)
several ways to output annotations.

Since the OAS community continues to hotly debate whether
"document", "describe", or "define" is most correct, ``oascomply`` refers
to the OAS-compliant thing associated with an API as an **APID**,

This tool is designed to support OAS 3.0 and 3.1, and be extensible to any
future versions.  During the current pre-release phase, OAS 3.0 is the only
fully supported version, with 3.1 support expected by the end of 2023.


JSON and YAML are both supported, but note that for very large files,
JSON is significantly faster to parse.
