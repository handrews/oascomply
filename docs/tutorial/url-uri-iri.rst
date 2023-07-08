URLs, URIs, IRIs, etc.
======================

There is a lot of confusion over when and why to use each of these terms.
``oascomply`` attempts to be consistent with the following guidance.

Location vs Identity: URLs vs URIs / IRIs
-----------------------------------------

**URLs** are URIs (or IRIs) that are *intended* to be used to locate and
interact with a resource.

While RFC 3986 defines both terms and recommends only using URI, using
both terms correctly with technical audiences adds clarity.  (Non-technical
audiences, of course, only understand "URL".)

URIs that are truly also URLs include:

* API endpoint URIs
* URIs or equivalents (local paths) given as user input for document loading
* URIs such as ``data:`` URIs that embed the resource in the URI/URL itself

``oascomply`` separates APID document location (URL) and identity (URI)
to support different development and production environments:

* development environments often involve local files, with file extensions
  to support tools such as syntax highlighting
* production environments are often network-based, such as HTTPS resources
  where the format (e.g. JSON vs YAML) is selected by HTTP content negotiation

References (``"$ref"``) are assumed to be written using the URIs of the
*production* environment, while a tool like ``oascomply`` most often loads
APIDs from a development or testing environment.  Assuming the development
and production environemnts described above:

* If ``oascomply`` is run agains the production environment, then the APID
  documents' URLs and URIs will be identical (``https:`` URLs without
  file extensions)
* If ``oascomply`` is run against a development environment, then the URLs
  will be ``file:`` URLs that will include any ``.json``, ``.yaml``,
  etc. file extensions, while the URIs will be ``https:`` URIs without them

This separation is critically important when running against a development
or testing version of a deployed API:  Using the APID URIs as URLs would load
the production documents, which would be bad!  This is why ``oascomply`` is
very careful about URI vs URL even when the URI in question *appears* to
be usable as a URL.

For guidance on configuring ``oascomply`` for a variety of development and
deployment scenarios, see :doc:`../tutorial/loading`.

For guidance on interpreting URIs (including URLs) in ``oascomply`` output,
see: :doc:`../tutorial/output`.

URLs and WHATWG
+++++++++++++++

WHATWG's URL "living standard" is about parsing and serializing URLs in the
context of web browsers.  URIs have a broader purpose than that, and despite
its audacious claims to "obsolete" RFC 3986, WHATWG's spec does not even cover
all of RFC 3986's topics.

While WHATWG's spec should be followed if you wish to implement or emulate
a browser, the OAS only cites RFC 3986 for all of its URI- and URL-related
topics.  Therefore ``oascomply`` strictly adheres to RFC 3986 and ignores
WHATWG.

URIs vs IRIs
------------

IRIs are essentially URIs with full unicode support (for a more precise
definition, see RFC 3987).

Since OAS 3.x only supports URIs, any IRIs that need to appear in APIDs
must be encoded into URIs as specified by RFC 3987 section 3.  ``oascomply``
treats APID contents as URIs only.

``oascomply`` also uses Semantic Web technologies such as the Resource
Descrption Framework (RDF), which are all defined in terms of IRIs.
***TBD:* Should ``oascomply`` un-encode encoded IRIs from APIDs before
adding them to RDF graphs?  It would be more human-friendly.**

a resource identifier is

as URIs.  Since

(URLs) from identity (URIs) so that APIDs
can be loaded from a local environment (often a local filesystem, with file
extensions to support syntax highlighting and other tools) even with
references (``"$ref"``) that assume a deployed production environment
(HTTPS access without file extensions, using content negotiation to select
the format such as JSON vs YAML).

Examples of URIs or IRIs that are URLs include:

* API endpoint URIs
* URIs or equivalents (e.g. local filesytem paths that can be converted to
  ``file:`` URIs) provided as user input telling programs how to interact
  with a resource
* URIs such as ``data:`` URIs that embed the resource in the URI/URL
* IRIs for an RDF (Resource Description Framework) ontology that is
  intended to be downloaded and used by RDF processing tools

``oascomply`` makes a strong distinction between URLs and
URIs for APID documents.  Each document is assigned:

* a *URL* based on how it was loaded (e.g. a ``file:`` URL including any
    file extension if it was loaded from the local filesystem)
* a *URI* that is used for resolving references (``"$ref"``), which may
    or may not be the same as its URL

This is so that ``oascomply`` can APID can contain references written for the deployed
production environment (e.g. HTTPS access without a file extension, with
file format determined by HTTP request and response headers)
Most APID authors write references based on the deployed production location
of the APID documents, which are often HTTPS-accessible network resources
without a file extension.
Common use cases for separating location (URL) and identity (URI) include:

Note that "IRL" is never used as the IRI equivalent of URL.  In practice,
the usage of IRIs as URLs tends to e clear from context.

**IRIs** are essentially URIs with full unicode support (for precise
details, see RFC 3987).  OAS 3.x technially only supports URIs, although
IRIs can be written in a URI-compliant form per RFC 3987 section 3.

``oascomply`` internally treats identifiers within OAS APIDs as URIs, and
all other identifiers as IRIs to support non-ASCII language environments.


Semantic Web technologies such as RDF
(Resource Description Framework) are defined in terms of IRIs
User input instructing a program to

URIs/IRIs vs URI/IRI references vs relative references
------------------------------------------------------

Readers should understand the following terms from RFC 3986 and RFC 3987
(but see the next section of this document for URL vs URI), which are
summarized here for convenience.

====================== ======= ========= ======== ====================
term                   scheme? fragment? unicode? JSON Schema
====================== ======= ========= ======== ====================
URI                    yes     maybe     no       ``"format": "uri"``
URI-reference          maybe   maybe     no       ``"format": "uri-reference"``
relative URI-reference no      maybe     no
absolute-URI           yes     no        no
IRI                    yes     maybe     yes      ``"format": "iri"``
IRI-reference          maybe   maybe     yes      ``"format": "iri-reference"``
relative IRI-reference no      maybe     yes
absolute-IRI           yes     no        no
relative-referencde    no      maybe     maybe
====================== ======= ========= ======== ====================

The terms with hyphens ("URI-reference") may be written without the hyphen
without changing their meaning.

The term "relative reference" is ambiguous regarding

URL vs URI vs IRI vs relative references
----------------------------------------

**URLs** are URIs that are *intended* to be used to locate and interact
with a resource.  A give URL may not be usable depending on the application
configuration (e.g. permissions) or due to transient errors, but if it is
intended to be usable as a URL by anyone who should have access, then it
is a URL.

URIs that can safely be considered URLs include:

* API endpoints (their entire purpose is to faciliate resource interactions)
* Locations given by a user, whether as a URI, a local file path, or otherwise,
    to tell an applicaiton how to load a resource
* URIs such as ``data:`` URIs that embed the content in the URI/URL itself


Note that URIs such as those with ``https:`` schemes always appear to be usable
as URLs, but may not be intended as such.  For exa
of the URL at times, but if it is intended to be usable as a URL, then itThe following URIs can be considered URLs:

* **URI**: A full resource identifier, including a scheme
    (`https:`, `file:`, etc.), in accordance with RFC 3986; where the
    distinction between *URI* and *URI-reference* might be confusing,
    the term **full URI** is used
* **relative URI reference**: A partial URI, lacking a scheme,
    in accordance with RFC 3986 section 4.2
* **URI reference**: Either a *URI* or a *relative URI reference*,
    in accordance with RFC 3986 section 4.1
* **absolute IRI**: A URI (with scheme) that does not contain a fragment,
    in accordance with RFC 3986 section
* **IRI**, **IRI reference**, **relative IRI reference**, **absolute IRI**:
    Essentially URIs, etc., with full Unicode support; for the proper
    definition see RFC 3987; semantic web standards refer to IRIs rather
    than URIs, although ``rdflib`` confusingly uses a ``URIRef`` class
    despite supporting IRI references
* **URL** a URI (or, informally, IRI, as "IRL" is never used in this context)
    that is intended to be used to locate and interact with a resource;
    while only some URI schemes can be used in URLs, a scheme alone is not sufficient to indicate
    that a URI is a URL if the resource is never intended to be accessible
    through the URL-ish URI

