# MacroFinder — design direction

Implementation spec for M23/M24 of `docs/PLAN-V2.md`. Written to replace the
Material 3 defaults with a deliberate system.

**Dependency:** do not start this until M15/M16 (catalogue with image URLs) are
merged. A grocery list without product photos will look unfinished no matter how
good the type is — in this category the images carry the layout. Building the UI
first means building it twice.

---

## 1. Diagnosis: what makes a Compose app read as a prototype

Work through this list first. Most of the "prototype" feeling is these eight
things, and fixing them is mechanical.

1. **The generated palette is still there.** If `ui/theme/Color.kt` contains
   `Purple40`, `PurpleGrey40`, `Pink40`, the app is wearing the Android Studio
   new-project template. Delete the file's contents entirely.
2. **`dynamicColor` is `true`.** The template defaults it on, which makes the app
   adopt the user's wallpaper colours on Android 12+. The app has no identity of
   its own and looks different on every device. **Set it to `false`.** This is the
   single highest-impact line in the codebase.
3. **Typography is untouched `Typography()`.** That means Roboto at default sizes.
   Roboto is the most legible "stock Android" signal there is.
4. **Everything is an elevated `Card`.** `CardDefaults.cardElevation()` puts the
   same soft grey shadow under every row. Stacked, it reads as a debug view of a
   list rather than a designed list.
5. **Stock `Icons.Default.*` everywhere.** The Material icon set is instantly
   recognisable. Every one of them in a prominent position is a tell.
6. **Default `TopAppBar` and `TabRow`.** The M3 tab indicator and the default app
   bar colours are unmistakable.
7. **Numbers in proportional figures.** Prices and macros that don't align
   vertically column-to-column look amateur in a data-dense list. This is a
   one-line font-feature fix and it matters more than it sounds.
8. **16dp padding on everything.** No spacing rhythm means no hierarchy.

---

## 2. Design plan

### 2.1 Subject and audience

A price-per-gram-of-protein tool for people who lift, reading a Dutch supermarket
folder. The vernacular to draw from is the **voedingswaarde table on the back of a
pack** — dense, tabular, black on white, hairline rules, numbers doing the talking.
Not a wellness app, not a recipe app. Closer to a spec sheet than a lifestyle brand.

The primary job of every screen: let someone decide in about ten seconds whether a
deal is worth walking to the shop for.

### 2.2 Where the boldness goes

One bold element, everything else quiet: **the macro strip**. A tabular,
nutrition-label-derived block of figures with hairline rules, set in the app's
heaviest weight. It appears on the detail screen and in compressed form on list
rows. It is the thing that makes this app look like nothing else in the category,
and it is justified by the subject rather than decoration.

Everything surrounding it stays flat, white, and unremarkable. Resist adding a
second memorable thing.

### 2.3 Colour

```
Paper     #F5F7F4   page background — a whisper of green-grey, not white
Card      #FFFFFF   rows and sheets, flat, no shadow
Ink       #1A1D1B   primary text
Muted     #6E7573   secondary text, units, labels
Rule      #E3E7E2   hairlines, 1dp
Signal    #00694E   the single accent — primary actions, best-value marks
```

Cards separate from the background **by value, not by shadow**. `Card` on `Paper`
at zero elevation, 14dp radius. No `rgba(0,0,0,.1)` under anything.

**The only gradient in the app encodes deal quality.** Applied to the
€/100 g protein figure and nothing else:

```
excellent  #00694E     top decile for this food type
good       #3F7D68
average    #7C918A
poor       #6E7573     (falls back to Muted — no red, nothing is "bad")
```

Colour here is information, not decoration. If a value's provenance is uncertain
(BRIEF §9), it renders in `Muted` regardless of how good the number is.

**Chain identity: marks, not fills.** The current app uses the chain's own colour,
which is right in principle, but three saturated chips on one screen is three
colours fighting. Render chain as a **3dp coloured rule down the leading edge of
the row**, plus the chain's short name in `Muted`. AH red, Jumbo yellow, Aldi blue
stay accurate and stop shouting.

### 2.4 Type

**One family: Archivo**, via `androidx.compose.ui.text.googlefonts`. A grotesque
with strong, slightly condensed numerals — it holds up in dense price tables where
Inter goes soft, and it isn't the family every app reaches for.

```
Display    Archivo 600, 28sp, -0.5 tracking   screen titles
Title      Archivo 600, 19sp                  product names
Body       Archivo 400, 15sp, 1.45 line       descriptions, notes
Figure     Archivo 600, 22sp, tnum            prices, the macro strip
FigureSm   Archivo 500, 14sp, tnum            inline metrics in rows
Label      Archivo 500, 12sp                  units, chain names, badges
```

**Enable tabular figures on every numeric style:**

```kotlin
fontFeatureSettings = "tnum"
```

Without this, `€2,54` and `€11,90` in adjacent rows have different digit widths and
the price column visibly wobbles. With it, every column locks. This is the cheapest
large improvement available.

Labels are **sentence case**, never all caps. Dutch for anything user-facing —
"per 100 g eiwit", not "per 100g protein".

### 2.5 Spacing

A 4dp base with a restricted set: `4 · 8 · 12 · 16 · 24 · 32`. Nothing else.
Row vertical padding 12, horizontal 16, gap between card and card 8. The rhythm
doing the work, not dividers everywhere.

---

## 3. Layout

### 3.1 The ranked list row — the core screen

```
┌────────────────────────────────────────────────────┐
│▎  ┌────────┐  Magere kwark naturel          1 kg   │
│▎  │        │                                       │
│▎  │  IMG   │  [1+1 gratis]  [koop 2]               │
│▎  │  64dp  │                                       │
│▎  └────────┘  €2,54 per 100 g eiwit        €0,89   │
└────────────────────────────────────────────────────┘
 ▲                    ▲                         ▲
 chain rule      deal-quality colour        shelf price
```

- Target row height ~92dp. Fifty items inside two scrolls on a 6" screen.
- Image 64dp square, 8dp radius, `Coil` with a `Paper`-coloured placeholder.
- The sorted-on metric is always the coloured figure at bottom-left. Change the
  sort, the metric in that slot changes. One consistent place to look.
- Badges are outlined in `Rule`, `Label` type, 4dp radius — not filled chips.
- Unknown macros: the metric slot reads "eiwit onbekend" in `Muted`, and the row
  ranks last. Never hidden, never zero.

### 3.2 The macro strip — the one bold element

Detail screen, directly under the image. Hairline rules, tabular figures, the
label on the left and the number right-aligned so the column locks.

```
 ────────────────────────────────────────
  Eiwit                          10,3 g
  Per 100 kcal                   18,1 g
 ────────────────────────────────────────
  Per 100 g eiwit                €2,54
  Per 1000 kcal                  €8,90
 ────────────────────────────────────────
  Goedkoopste in 14 weken
```

Set in `Figure`. This block is allowed to be denser and heavier than anything else
on the screen. It is the app's signature.

### 3.3 Sort and filter

The review on Mandje's own listing asks for sorting by highest discount, so even
the incumbent is thin here. Make the sort control prominent — a row of text
buttons directly under the title, not buried behind an icon:

```
  Eiwit per euro   Per 100 kcal   Kcal per euro   Korting
  ─────────────
```

Active sort underlined in `Signal`. No dropdown, no bottom sheet, no icon button.
Four taps' worth of function should cost zero taps to discover.

---

## 4. Motion

One orchestrated moment: the list's first paint after a sync completes, a single
staggered fade. Nothing else.

No per-card entrance animations, no hover-equivalent transitions, no shimmer on
every placeholder. Motion that answers a tap — a sheet opening, a sort re-ordering
— is welcome and should show what changed. Respect the system reduced-motion
setting.

---

## 5. Copy

Dutch, sentence case, plain verbs. Names are what a user would say, not what the
system calls it.

- "Bewaar" not "Submit". The button that says "Volg product" produces "Gevolgd".
- Empty state is an instruction, not a mood: "Nog geen favorieten. Tik het hartje
  op een product om het te volgen." Never "Niets te zien hier :("
- Errors say what happened and what to do: "Prijzen konden niet worden bijgewerkt.
  Controleer je verbinding en trek omlaag om te vernieuwen."
- Never claim a DIY composition tastes the same — state the delta (BRIEF §9).

---

## 6. Implementation order

1. `dynamicColor = false`, delete the generated palette, install the tokens in §2.3.
2. Archivo + the type scale, `tnum` on every numeric style.
3. Strip elevation from every `Card`; white on `Paper`, 14dp radius.
4. Rebuild the list row to §3.1.
5. Chain chips → leading rule + `Muted` name.
6. Sort control to §3.3.
7. Macro strip on detail.
8. Audit every `Icons.Default.*` — replace or remove. Text beats a stock icon.
9. Motion pass: delete everything except the one sync reveal.

Steps 1–3 alone will account for most of the difference. They are a few hours of
work and they are why the app currently looks generated rather than designed.

---

## 7. Quality floor

Not optional, not worth announcing in the UI:

- Visible keyboard focus on every interactive element
- Touch targets ≥ 48dp
- Text contrast ≥ 4.5:1 — check `Muted` on `Paper` specifically, it is the one
  most likely to fail
- The deal-quality colour scale must never be the *only* carrier of information;
  the number itself is always present
- Dark theme derived from the same tokens, not a separate palette
- Tested at 200% font scale without clipping
