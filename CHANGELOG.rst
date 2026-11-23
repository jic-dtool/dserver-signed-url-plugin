Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.0.0/>`_,
and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.


Unreleased
----------

Changed
~~~~~~~

- Requires ``dtoolcore>=3.20.0`` (previously ``>=3.18.0``), the first release
  with ``ProtoDataSet.freeze_with_manifest``, which upload-complete uses
- Upload initiation and upload completion now return ``502 Bad Gateway``
  with an explanatory message when the storage backend rejects a
  server-side write (e.g. ``AccessDenied`` because the server's storage
  credentials lack write permission), instead of a generic ``500``


v0.1.0 (2025-12-08)
-------------------

Initial release of the dserver signed URL plugin.

Added
~~~~~

- Signed URL generation for reading datasets (``GET /signed-urls/dataset/<uri>``)
- Signed URL generation for individual items (``GET /signed-urls/item/<uri>/<identifier>``)
- Signed URL generation for uploading new datasets (``POST /signed-urls/upload/<base_uri>``)
- Upload completion endpoint (``POST /signed-urls/upload-complete``)
- Proto-dataset workflow for uploads:

  - Creates proto-dataset (``type: protodataset``) on upload initiation
  - Freezes to dataset (``type: dataset``) on upload completion
  - Validates README and all manifest items exist before freezing

- Database persistence for pending uploads:

  - ``PendingUpload`` model stored in SQL database (PostgreSQL/SQLite)
  - Tracks upload state across server restarts
  - Native JSON field for manifest storage

- CLI commands for pending upload management:

  - ``flask pending_upload list`` - List pending uploads
  - ``flask pending_upload cleanup`` - Clean up stale uploads
  - ``flask pending_upload delete`` - Delete specific pending upload

- URL rewriting support for containerized deployments
- Configurable URL expiry times via environment variables:

  - ``SIGNED_URL_READ_EXPIRY_SECONDS`` (default: 3600)
  - ``SIGNED_URL_WRITE_EXPIRY_SECONDS`` (default: 14400)

- Support for S3-compatible storage (via dtool-s3)
- Support for Azure Blob Storage (via dtool-azure)
- Comprehensive API documentation in README.rst
- End-to-end tests against a real S3 server (SeaweedFS in CI): signed
  upload URLs, upload-complete with dtool-s3, registration in dserver and
  signed read URLs. Run with ``DSERVER_S3_INTEGRATION_TESTS=1``

Dependencies
~~~~~~~~~~~~

- Requires Python 3.10 or later
- Requires ``dtoolcore>=3.18.0`` with ``freeze_with_manifest`` support
- Requires ``dservercore>0.18.0``
- Requires ``dtool-s3`` for S3/MinIO backends
- Optional ``dtool-azure`` for Azure backends
- Built with ``hatchling`` and ``hatch-vcs``; the version is derived from git tags
