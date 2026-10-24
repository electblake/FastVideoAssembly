---
name: strict-ui-text
description: Enforce functional, nonredundant UI text when creating, modifying, or reviewing this project's interfaces. Treat explanatory filler, duplicated control values, and decorative separators as regressions.
---

# Strict UI text policy

Use functional controls, never explanatory filler.

Text is permitted only as component titles, form labels, buttons, menus, tabs, options, placeholders, useful tooltips, actual content/results, or necessary status/error messages. These locations do not excuse redundancy.

Never add:
- Standalone explanations, tutorials, or descriptions of controls.
- Text repeating visible selections, states, options, or settings.
- Static prose describing defaults, presets, behavior, or implementation details.
- Duplicate information across components or text added to fill space.
- Decorative dots, bullet separators, or em dashes.
- Prose substituting for a missing setting control.

A visible control communicates its own value. Never restate it elsewhere. Expose configurable behavior through controls.

Remove redundant text and unused layout space. Never relocate it into tooltips, panels, banners, or status bars, or replace it with other filler. Preserve actual content and necessary operational feedback.

Every violation is a regression. Check for and fix these patterns whenever creating, modifying, or reviewing the affected UI. For review-only requests, report the regressions without editing files. Text must serve a necessary component function, add nonduplicative information, and not belong in a control instead. Otherwise remove it.
