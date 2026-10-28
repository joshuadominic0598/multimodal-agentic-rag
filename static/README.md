# Frontend

The browser interface lives in this `static/` directory. It uses HTML, CSS and vanilla JavaScript, served by the local Python application. There is no Node build step or frontend package install.

The [main README](../README.md) is the product walkthrough. Server setup, data flow, service adapters and operational limits belong in the [backend README](../app/README.md).

## Files

| File | Responsibility |
|---|---|
| `index.html` | Document title, boot screen, stylesheet/script loading and favicon |
| `app.js` | Screen rendering, form state, local API requests, background job polling and source viewers |
| `style.css` | Responsive layout and the fixed dark theme |
| `icon.svg` | Original application icon, unchanged by the product rename |

## Screens

- **Source library:** uploads, local folder browsing, URL import and working-source selection.
- **Azure workspace:** existing-resource setup, authentication, access checks, cloud operation review and publication history.
- **Processing studio:** retrieval mode, local/Azure extraction, element inspection, preprocessing, chunk previews, field attributes and index creation.
- **Research agent:** clarification, conversational follow-ups, investigation/context controls, citations, source cards, media references and scoped memory.
- **Monitoring:** job events, provider/service usage, quota failures and known/unpriced costs.
- **Evaluation lab:** ground-truth import, model selection, run progress, metrics and human review.
- **Connections & settings:** provider discovery, saved model profiles, capability tests, context/output settings and workspace guidance.

## Run and edit

From the project root, use `start.command` after the backend environment is installed. Edit the files in place and reload the browser. `AGENTIC_RAG_PORT` changes the default port, 8020. The server serves `/static/` directly and sets no-store response headers.

The script uses same-origin `/api/` requests with `X-Agentic-RAG-Client: local-workspace`. JSON and file uploads use the same request helper. Keep this header synchronized with the local-origin guard in `app/main.py`.

Only working-source and pipeline preferences belong in browser local storage. Credentials stay on the server and are write-only in API responses. Preferences with an earlier branding prefix are migrated by suffix when the page loads. Model discovery uses an explicit form action; changing a provider or tier does not trigger generation or modify account billing.

## Appearance and source rendering

Keep the fixed dark palette in this order: black, grey, blue, purple, orange. The sidebar uses **Agentic RAG** and **Document Knowledge Studio** with the original icon. Native controls use a dark color scheme. Maintain readable source cards, tables, code and modal content at narrow widths.

Source text is escaped before rendering. Imported HTML and code are served as downloads, rather than executed. Original image/table previews and audio/video timestamps stay attached to source cards. The UI distinguishes image understanding, image embedding and image generation; unsupported capabilities should remain visible to the user.

## Verification

Check JavaScript syntax with `node --check static/app.js`. Run backend contract tests from the project root with `.venv/bin/python -m pytest -q`. For browser changes, inspect the affected screens, provider forms, source dialogs and responsive overflow in the running app. Actual screenshots live in `resources/images/`; architecture and Azure workflow diagrams are generated from `docs/diagrams/`.
