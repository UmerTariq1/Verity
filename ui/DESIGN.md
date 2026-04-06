# Design System Specification: The Cognitive Atelier

## 1. Overview & Creative North Star
This design system moves beyond the "utility dashboard" aesthetic to establish **The Cognitive Atelier**. 

The North Star of this system is "Architectural Intelligence." Instead of a flat grid of data, we treat knowledge retrieval as a high-end editorial experience. We achieve this through **Intentional Asymmetry** and **Tonal Depth**. By leaning into a "Soft Minimalist" approach, we prioritize focus and clarity. We break the template look by using overlapping layers and high-contrast typography scales that make the platform feel like a curated workspace rather than a generic database.

---

## 2. Colors & Surface Philosophy
The palette is rooted in a sophisticated Teal (`primary`), supported by a multi-tonal Indigo (`secondary`) and Violet (`tertiary`). 

### The "No-Line" Rule
To achieve a premium feel, **1px solid borders for sectioning are strictly prohibited.** Boundaries must be defined through background color shifts or subtle tonal transitions. 
*   **Example:** A `surface-container-low` (`#f3f4f6`) section should sit directly on a `surface` (`#f8f9fb`) background without a stroke.

### Surface Hierarchy & Nesting
Treat the UI as physical layers—stacked sheets of frosted glass and fine paper.
- **Surface (Base):** `#f8f9fb`
- **Surface-Container-Low:** `#f3f4f6` (Use for secondary content areas)
- **Surface-Container-Lowest:** `#ffffff` (Use for the "active" card or workspace)

### The "Glass & Gradient" Rule
Floating elements (Modals, Popovers) must utilize **Glassmorphism**. Use semi-transparent surface colors with a `20px` backdrop-blur. 
*   **Signature Texture:** Main CTAs or Hero backgrounds should use a subtle linear gradient from `primary` (`#006b5f`) to `primary_container` (`#14b8a6`) at a 135-degree angle to provide a "soul" that flat hex codes lack.

---

## 3. Typography
We utilize a dual-font strategy to balance authority with readability.

*   **Display & Headlines (Manrope):** Chosen for its geometric precision. Use `display-lg` (3.5rem) and `headline-md` (1.75rem) to create editorial "breathing room." Bold weights should be reserved for primary entry points.
*   **Body & Labels (Inter):** The workhorse. `body-md` (0.875rem) is the standard for knowledge retrieval. 
*   **The Intentional Scale:** Always jump at least two steps in the scale when transitioning from a header to a sub-header to ensure a "Designed" look. Never use 14pt and 16pt text next to each other.

---

## 4. Elevation & Depth
Hierarchy is achieved through **Tonal Layering** rather than structural lines.

*   **The Layering Principle:** Place a `surface-container-lowest` card on a `surface-container-low` section. This creates a natural "lift" without the "muddy" look of traditional shadows.
*   **Ambient Shadows:** If a card must float, use an extra-diffused shadow: `0px 20px 40px rgba(25, 28, 30, 0.06)`. Notice the tint—we use a tiny fraction of the `on-surface` color, never pure black.
*   **The "Ghost Border":** If accessibility requires a container edge, use the `outline-variant` token at **15% opacity**.
*   **Edge Accents:** Per the brand signature, cards utilize a `4px` solid left-border using semantic tokens (e.g., `primary`, `secondary`, or `tertiary`) to denote status or ownership without cluttering the card face.

---

## 5. Components

### Buttons
- **Primary:** Gradient fill (`primary` to `primary-container`), `xl` (1.5rem) roundedness.
- **Secondary/Tertiary:** No background. Use `primary` text and a `surface-variant` hover state.
- **Micro-interaction:** On hover, a subtle scale-up (1.02x) with a `300ms` ease-out.

### Input Fields
- **Styling:** Large (48px height), `surface-container-lowest` fill, no border. 
- **Focus State:** A `2px` soft glow using `primary` at 20% opacity. 
- **Labels:** Use `label-md` in `on-surface-variant` positioned 8px above the input.

### Cards & Lists
- **The "No Divider" Rule:** Forbid the use of divider lines. Separate items using `16px` of vertical white space or alternating `surface-container` shifts.
- **List Items:** Use `surface-bright` for the hover state to make the item "pop" forward.

### Signature Component: The Knowledge Leaf
For the Intelligent Retrieval context, search results should appear as "Leaf" components—cards with an asymmetrical `1.5rem` radius on the top-left and bottom-right corners, and a `0.25rem` radius on the others, creating a custom, organic feel.

---

## 6. Do's and Don'ts

### Do:
*   **Do** use white space as a structural element. If a section feels crowded, increase the padding to the next step in the scale before adding a line.
*   **Do** use `secondary` (Indigo) for user-generated content and `tertiary` (Violet) for system-generated admin actions to maintain cognitive separation.
*   **Do** apply `skeleton-loaders` that mimic the exact typography height of the final content to prevent layout shift.

### Don't:
*   **Don't** use 100% black text. Always use `on-surface` (`#191c1e`) for a softer, more professional contrast.
*   **Don't** use "Drop Shadows" on flat surfaces. Depth should be a result of color-stacking first.
*   **Don't** use the `full` (9999px) roundedness for anything other than tags or chips. Buttons and cards must maintain the `xl` or `lg` professional radii.