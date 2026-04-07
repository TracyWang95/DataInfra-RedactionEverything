# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
Backward-compatible re-export hub -- all existing imports continue to work.

Domain files:
  common.py           — Shared enums, base models, generic responses, auth
  entity_schemas.py   — Entity, BoundingBox, custom entity types
  redaction_schemas.py— RedactionConfig/Request/Result, preview, compare, report
  job_schemas.py      — Job CRUD, progress, review-draft bodies
  file_schemas.py     — File upload/list/parse/NER, batch download
  vision_schemas.py   — VisionResult, HybridNERRequest
  config_schemas.py   — ModelConfig, ModelConfigList
  preset_schemas.py   — Preset CRUD models
"""
from .common import *            # noqa: F401,F403
from .entity_schemas import *    # noqa: F401,F403
from .redaction_schemas import * # noqa: F401,F403
from .job_schemas import *       # noqa: F401,F403
from .file_schemas import *      # noqa: F401,F403
from .vision_schemas import *    # noqa: F401,F403
from .config_schemas import *    # noqa: F401,F403
from .preset_schemas import *    # noqa: F401,F403
