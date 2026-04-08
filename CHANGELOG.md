# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Security

### Removed

## [1.0.0] - 2026-04-07

### Added
- Batch processing workflow with four-step pipeline (upload, configure, execute, review)
- Re-run recognition button in batch step 4 review
- Click entity mark to show remove popover (matching Playground pattern)
- Cycle through entity occurrences on click with synced preview scroll
- Text selection annotation in batch step 4
- Custom entity type option in annotation popovers
- Apple-style hero typography on upload page
- Compliance standards reference line on upload page
- Image comparison in history compare dialog
- Bilingual README with language switcher (EN / 中文)
- Bilingual CONTRIBUTING.md aligned with current toolchain
- Docker Compose deployment with CPU-only default and optional GPU profile
- `.dockerignore` and `.env.example` for streamlined Docker builds
- End-to-end (E2E) test suite

### Changed
- Rebranded UI terminology from 脱敏 to 匿名化 across playground, batch, and settings
- Redesigned text annotation popovers to minimal ShadCN style
- Improved batch step 4 text review with five usability enhancements
- Shrunk batch step 4 annotation popover to fit smaller canvas (220 px, 2-col)
- Refined playground sidebar layout, spacing, and footer alignment
- Constrained all pages to viewport height via Layout `h-dvh`
- Aligned frontend TypeScript types with backend Pydantic models
- Improved frontend offline states and UI stability
- Updated playground upload text to reference unstructured data and anonymization
- Default README language set to Chinese with prominent license notice
- Updated contact email

### Fixed
- Portal loading overlay now covers sidebar by rendering to `<body>`
- Batch review popover dismisses on scroll; playground entity map counts corrected
- Popover scroll, sizing, and layout issues
- Tooltip spans removed from mark tags (they broke offset calculation)
- Click-to-upload and infinite page overflow at 100 % zoom (Chrome compatibility)
- `dropzone.open()` used for click-to-upload for Chrome compatibility
- `className` override removed from dropzone input
- Text section hidden for image comparison in history dialog
- Stale job error in batch step 4

### Removed
- Dead Celery + Redis code and stale Celery references in comments
- Deprecated scripts, legacy tests, and local cruft
- Boilerplate CODE_OF_CONDUCT.md
- Batch execution path selector
- Per-type count summary from mapping column header
- Dead `entities` prop from MappingColumn chain
- Dark mode claim and air-gapped wording from READMEs
- Internal-only files cleaned up for open-source release
