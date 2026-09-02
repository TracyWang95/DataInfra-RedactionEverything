# DICOM compatibility toolkit

Run commands from the repository root with the backend virtual environment.

```powershell
.venv\Scripts\python.exe tools\dicom_compat\fetch_samples.py
.venv\Scripts\python.exe tools\dicom_compat\generate_synthetic_cases.py --clean
.venv\Scripts\python.exe tools\dicom_compat\fetch_dcmtk.py
.venv\Scripts\python.exe tools\dicom_compat\validate_corpus.py `
  --decode-pixels --independent --require-independent `
  --report backend\tests\assets\dicom\reports\corpus.json
```

`fetch_samples.py` verifies pinned sizes and SHA-256 hashes.  Pytest never
downloads fixtures, so offline CI is deterministic: provision the cache in a
separate job or accept explicit skips.

`validate_corpus.py` records structured risk counts, pixel decode state and
external-parser status.  It intentionally omits attribute values and external
tool output.  `compare_outputs.py` verifies an exported anonymized tree against
its source, including de-identification tags, changed identifiers, UID mapping
consistency, private tags, clinical geometry, frame counts and pixel hashes.

The two network probes are opt-in:

```powershell
# Read-only QIDO-RS
.venv\Scripts\python.exe tools\dicom_compat\dicomweb_probe.py `
  --base-url http://127.0.0.1:8042/dicom-web

# DIMSE C-ECHO
.venv\Scripts\python.exe tools\dicom_compat\dimse_probe.py 127.0.0.1 4242 `
  --called-aet ORTHANC
```

STOW-RS and C-STORE require an explicit file plus `--allow-write`; the probes
never write to a remote system merely because an endpoint was supplied.

