# SurePlace Known Issues

Last updated: 2026-09-08

## Open Before Launch

- Backend tests could not be executed in this workstation session because Django is not installed on the active Python path. Run the backend suite from the project virtual environment before release.
- No live or staging server was available in this session, so real authentication, API permissions, uploaded media rendering, email delivery, and external storage behavior were not end-to-end verified.
## Watch Items

- Verification request creation requires the user to provide the related entity ID for agent, agency, property, or stay verification. The backend validates ownership, but a future UX pass should replace manual IDs with selectable owned entities.
- The Angular project has no `lint` script configured yet. Current local and CI checks cover install, audit, tests, and production build.
- Leaflet remains a CommonJS dependency and is explicitly allowed in Angular build configuration. Revisit if the map implementation moves to an ESM-native provider.
- Page styles for the home and stay search screens are bundled globally to avoid component-style budget warnings. The selectors are page-scoped, but future style edits should keep them namespaced.

## Recently Closed

- Property and stay forms now include a map-based location picker while keeping numeric latitude/longitude fields for precise edits.
- Property, stay, and room images now support reorder, set cover, and delete actions in the manager UI.
- Verification requests can now be created from the frontend and then moved through the existing document upload and submit flow.
- Frontend production build warnings for oversized component styles and Leaflet CommonJS output are cleared.
