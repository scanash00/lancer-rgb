# Lancer RGB design

Native Linux utility; the user is choosing colors, not administering SMBus.
The primary surface is an Operate surface in Impeccable's terminology.

- The color picker is the primary interaction. No separate color-dialog workflow.
- Native libadwaita typography, controls, focus and semantic accent colors.
- Dark preferred for judging emitted colors; system light preference respected.
- 4/8/12/16/24 spacing rhythm, restrained 12 px panel corners.
- Per user request, each module uses a proportional Lancer Blade side illustration:
  black heatsink, diagonal ribs, XPG/DDR5 side lettering and gold contacts. The
  continuous diffuser interpolates the eight actual LED colors. Keep the module
  labels and reported color values outside the artwork. No fake online indicators,
  marketing headings or technical labels in ordinary controls.
- Hex is directly editable; RGB numeric precision is available through disclosure.
- Live changes and persistent saves are separate actions and states.
- Read values, proposed preview values and last applied values have distinct labels.
- Hardware reads never trigger live writes. Known matching brightness is preserved.
- Narrow windows stack controls and hide only redundant footer text; content scrolls.
- Arrow-key alternatives and native numeric inputs complement pointer interaction.

Reviewed using Impeccable's core, Operate, polish and craft-floor references:
https://github.com/pbakaus/impeccable
GNOME HIG: https://developer.gnome.org/hig/

Verification: rendered 820×770 and 440×820 GTK windows; input, layout, debounce,
readback and persistence tests. Screenshot is demo data, not a hardware claim.

Module silhouette reference: https://gzhls.at/pix/0e/34/0e340ed036950886-l.webp
The preview is drawn in Cairo; no product-photo pixels are bundled.
