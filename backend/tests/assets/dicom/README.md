# DICOM test assets

This directory intentionally contains no clinical binary data in Git.

- `manifest.json` pins every public fixture to an immutable upstream commit,
  byte size, and SHA-256 digest.
- `tools/dicom_compat/fetch_samples.py` downloads the selected fixtures into
  the ignored `cache/` directory and verifies them before use.
- `tools/dicom_compat/generate_synthetic_cases.py` creates deterministic fake
  PHI, malformed input, a multi-study batch, and a ZIP archive in the ignored
  `generated/` directory.

The pydicom fixtures are documented upstream as test images that were
downsized and, where necessary, binary-edited to replace patient names.  The
GDCMData repository has no top-level dataset licence, so those files are
**local-fetch-only** and must not be copied into releases or redistributed
without a separate legal review.  The selected GDCM CR and DX cases contain
the explicit test identities `Anonymized` and `Overlay Patient`; the public
DX JPEG 2000 sample was deliberately excluded because its identifiers did not
look demonstrably synthetic or de-identified.

Never add hospital, customer, or ad-hoc internet DICOM files here.  Real-site
validation data belongs in an access-controlled, non-repository location and
must have a documented data-use basis.

