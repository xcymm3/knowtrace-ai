<!-- Hallmark · macrostructure: Workbench · theme: studied-DNA (source: image)
     paper: oklch(98% 0.004 250) · accent: oklch(59% 0.19 259)
     display/body: neutral grotesque · label: mono · studied: yes · DNA-source: image -->

# Design — KnowTrace AI

Locked design system. Future Hallmark runs read this file first; pages defer to
it. Amend intentionally — the file is the rule.

## System

- Genre · modern-minimal
- Macrostructure · Workbench: persistent project rail + focused reading canvas
- Theme · studied-DNA (vibe: "cool white, blue focus, utilitarian workbench")
- Axes · light / neutral-grotesque / cyan-blue

## Provenance

Extracted from an image supplied by the user on 2026-08-07. Tokens are
estimated from the screenshot's colour bands; typefaces are role-based
candidates rather than identified fonts. Rhythm was observed as medium-density,
left-biased desktop application chrome.

## Tokens

`tokens.css` is the runtime source of truth.

```css
:root {
  --color-paper: oklch(98% 0.004 250);
  --color-paper-raised: oklch(100% 0 0);
  --color-ink: oklch(24% 0.014 255);
  --color-ink-soft: oklch(39% 0.012 255);
  --color-rule: oklch(89% 0.009 255);
  --color-accent: oklch(59% 0.19 259);
  --color-accent-ink: oklch(100% 0 0);
  --color-focus: oklch(54% 0.2 259);

  --font-display: "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif;
  --font-body: "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif;
  --font-mono: "Sarasa Mono SC", Consolas, monospace;

  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-short: 140ms;
  --dur-medium: 220ms;
  --radius-control: 0.5rem;
  --radius-pill: 999px;
}
```

## CTA voice

- Primary · solid blue fill, white text, compact 8px radius.
- Secondary · white or transparent fill, cool-grey hairline border.

## Motion stance

- Motion-cut by default; only background, opacity and 1px transform feedback.
- Reduced-motion fallback · immediate state or ≤150 ms opacity crossfade.

## Notes

- Preserve the persistent side rail, thin neutral dividers and unboxed reading canvas.
- Use blue only for current selection, focus and the primary action.
- Do not copy the reference product's logo, labels, version information, menu taxonomy or content.
- Do not introduce glassmorphism, large gradients, dense card grids or decorative illustration.
