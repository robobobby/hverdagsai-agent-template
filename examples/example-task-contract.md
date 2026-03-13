# Task Contract: 01EXAMPLE1234567890ABCD

## Objective
Add a dark mode toggle to the settings page that persists the user's preference in localStorage.

## Non-Goals
- Full theme system (this is just light/dark toggle)
- Server-side theme persistence

## Context
The app uses Tailwind CSS with a custom color palette defined in `tailwind.config.ts`. The settings page is at `src/pages/Settings.tsx`. No existing dark mode infrastructure.

## Constraints
### Hard (must satisfy)
- Must work without JavaScript disabled (SSR-safe fallback)
- No flash of wrong theme on page load
- Accessible: meets WCAG 2.1 AA contrast ratios in both modes

### Soft (prefer but negotiable)
- Animate the transition between themes
- Respect system preference as default

## Dependencies
- None (standalone task)

## Acceptance Criteria
- [ ] Toggle visible on settings page
- [ ] Clicking toggle switches between light and dark themes
- [ ] Preference persists across page reloads (localStorage)
- [ ] No flash of unstyled content on initial load
- [ ] All text meets WCAG 2.1 AA contrast ratios in both modes
- [ ] Tests cover toggle behavior and persistence

## Context References
- Shared context version: 2026-03-13
- Tailwind config: `tailwind.config.ts`
- Settings page: `src/pages/Settings.tsx`

## Secret References
- None

## Routing Metadata
- Priority: 3
- Confidence: high
- Complexity: moderate
- Risk level: low
- Cross-cutting concerns: accessibility, UX consistency

## Escalation Triggers
- If Tailwind dark mode setup requires config changes beyond `darkMode: 'class'`
- Absolute timeout: 60 minutes
