# Arline Studio Reference Guide - Design QA

Source visual truth: `C:/Users/Revian/Downloads/Documents/Arline_Studio_UI_Reference_Guide.pdf`, especially pages 3-4.

Implementation evidence:

- `E:/Developen/Github/Arline Studio/tmp/design-qa/palette-desktop.png`
- `E:/Developen/Github/Arline Studio/tmp/design-qa/corkboard-desktop.png`
- `E:/Developen/Github/Arline Studio/tmp/design-qa/compare-palette.png`
- `E:/Developen/Github/Arline Studio/tmp/design-qa/compare-corkboard.png`

Viewport: 1280 x 720 CSS pixels for desktop; 390 x 844 CSS pixels for responsive checks.

Source pixels: rendered PDF pages are 1012 x 1434 pixels at 1.7 scale. Relevant source regions were cropped and proportionally contained beside 1280 x 720 implementation screenshots. No density-based measurements were treated as exact because the source is a conceptual document rather than an application screenshot.

State: dark theme, empty default project. The palette contains real navigation, command, and world results. The Corkboard and Outliner show truthful empty states because the selected project has no scene documents.

## Full-view comparison evidence

- Unified palette: the implementation follows the guide's restrained dark command surface, unified resource list, resource-type labels, keyboard actions, and contextual preview. It extends the sketch with the requested Peek behavior while preserving Arline's teal/charcoal identity.
- Manuscript planning: the implementation keeps Binder navigation, exposes Editor/Corkboard/Outliner as presentations over the same documents, and keeps the right Inspector stable. The source contains sample scene cards; the live project correctly renders an empty state instead of fabricated records.

## Focused-region comparison evidence

Focused comparison was required because the source's palette actions and manuscript view controls are too small to judge from full-page PDF renders. `compare-palette.png` verifies result hierarchy, type labels, keyboard affordances, and preview actions. `compare-corkboard.png` verifies Binder placement, planning header, mode switch, primary action, and Inspector placement.

## Required fidelity surfaces

- Fonts and typography: the existing system sans and monospace command accents preserve the reference hierarchy. Display headings, compact resource labels, and keyboard hints remain legible at desktop and mobile widths.
- Spacing and layout rhythm: palette and planning surfaces use restrained borders, consistent section spacing, and the reference's calm shell. No page-level horizontal overflow was present at 1280 or 390 pixels.
- Colors and visual tokens: charcoal surfaces, subdued inactive navigation, and teal emphasis align with the guide's stated Arline identity. Contrast remains strongest on selected and primary states.
- Image quality and asset fidelity: these reference sections contain interface diagrams rather than required raster imagery. The implementation reuses the existing Arline brand asset and the project's established icon library; no placeholder imagery or CSS-drawn product art was introduced.
- Copy and content: labels match the guide's interaction language: Search Arline, Corkboard, Outliner, Open, Add to Chat, Inspect, POV, Location, Words, and Continuity.

## Comparison history

1. P2 - Mobile Manuscript width: the inherited desktop grid kept a 235-pixel Binder track after the Binder was hidden, narrowing Outliner. Fixed by restoring a one-column Manuscript grid at the mobile breakpoint. Post-fix evidence measured the planning pane at 390 pixels with document scroll width equal to viewport width.
2. P2 - Mobile Library and global search cascade from the preceding visual pass: explicit mobile layout and compact palette trigger rules remain intact. Verified at 390 pixels without page overflow.

## Interaction verification

- Ctrl+K opens the global palette.
- Search filtered `dialogue` to `/dia`.
- Ctrl+Enter transferred `/dia ` into the Chat composer.
- Escape closes the palette.
- Corkboard and Outliner switches render their correct surfaces.
- Scene-card reads and writes use the backend `scene_cards` response and `saveSceneCard` endpoint.
- Browser console: zero warnings and zero errors during the tested flow.

## Findings

No actionable P0, P1, or P2 findings remain. The only intentional difference is that live scene cards are not fabricated when the active project is empty.

## Follow-up polish

- P3: validate populated Corkboard drag ordering with a real user project containing multiple scenes.
- P3: add richer continuity badges when the backend exposes per-scene warning counts directly in the scene-card list.

final result: passed
