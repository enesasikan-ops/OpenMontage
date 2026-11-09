---
name: jone-kebab-brand
description: JONE KEBAB house style - the visual DNA extracted from the brand's own posts (hand-held hero food shots, branded red/white packaging, golden light, logo top-right) plus ready prompt templates for Nano Banana (Gemini image) and image-to-video food motion shots. Use whenever making any image, carousel, reel, TikTok, ad or video for JONE KEBAB, or when the user says "comme mes publications", "même qualité", "style JONE", or asks for kebab / wings / frites / tenders visuals for their restaurant.
---

# JONE KEBAB - house style

Extracted from 5 reference posts made by the owner (4 photos + 1 slow-motion clip).
Reference files (not committed, live in the gitignored workspace):
`projects/jone-kebab-analyse/references/` - if missing, ask the user to re-upload them.

| # | File | What it shows |
|---|------|---------------|
| 01 | `01-kebab-mains-satin.jpg` | Woman in blush satin halter top holds the kebab (panini bread) with both hands at chest height, face cropped at the lips, gold ring, warm amber curtain backdrop. 4:5. |
| 02 | `02-wings-sauce-golden-hour.png` | Hand dips a glazed chicken wing into a sauce cup, sauce drip mid-air. Branded white box (red "JONE KEBAB", red "9" corners), red fry carton, branded cup, orange wooden picnic table, golden-hour backlight, navy hoodie. 3:4. Made with Gemini (sparkle watermark bottom right). |
| 03 | `03-sac-rue-pietonne.png` | Man walking on a sunny European cobblestone pedestrian street with café terraces, carrying a kraft paper bag: red "JONE KEBAB" logo, red bottom band, red rope handles. Face cropped at the smile. 1:1. |
| 04 | `04-frites-cornet-rouge.png` | Red fry carton with white logo, one hand pulling fries, white hoodie, dark wood table, plain beige wall. 1:1. |
| 05 | `05-cheese-pull-slowmo.mov` | 1.8 s, 9:16 macro slow motion: breaded cheese stick pulled apart by two hands (nude manicure), long cheese stretch, steam wisps, dark olive velvet backdrop, warm side key light. Image-to-video AI shot. |

## The DNA (every new visual must hit all of these)

1. **Food is the hero, the person is the frame.** Hands holding, dipping, pulling, carrying.
   Faces are cropped (lips / chin / smile at most), never a full face. This keeps it premium, avoids
   uncanny AI faces, and lets anyone picture themselves.
2. **Photoreal commercial-UGC.** Looks like a real phone/DSLR photo by a good food photographer:
   shallow depth of field (f/1.8-2.8 look), creamy bokeh, real skin texture, crumbs, gloss, steam.
3. **Warm light.** Golden hour, warm window light or a warm side key. Amber/honey highlights,
   never cold or flat studio white.
4. **Packaging is always branded and consistent:**
   - Brand red ~ `#E3200F` (shot in light it reads `#E81D06`-`#A81501`), white, kraft brown.
   - Logo = **"JONE" over "KEBAB"**, heavy italic geometric sans (Montserrat Black Italic /
     Poppins Black Italic family), tight tracking, KEBAB smaller and centered under JONE.
   - White box with red logo + red "9" in corners; red fry carton with white logo; kraft bag with
     red logo, red bottom band, red rope handles; white cup with red stripe + logo.
5. **Overlay:** white "JONE / KEBAB" logo, top-right corner, ~22% of image width, no other text.
   Add it in post (ffmpeg / Remotion), never ask the image model to draw the overlay.
6. **Formats:** 4:5 (1080x1350) for feed, 1:1 (1080x1080), 9:16 (1080x1920) for Reels/TikTok.
7. **Clothing palette:** soft solids (blush satin, navy hoodie, white hoodie, khaki bomber), no
   logos except JONE KEBAB.
8. **Backgrounds:** warm and blurred - amber curtain, olive velvet, beige wall, sunny street,
   wooden picnic table. Never cluttered, never pure black.

## Tooling (OpenMontage)

- **Images:** `google_imagen` tool with model `gemini-3-pro-image` (Nano Banana Pro) for heroes,
  `gemini-nano-banana-2.1` for drafts. Pass up to 14 reference images: ALWAYS pass at least one
  of the reference posts above + a clean packaging shot so the logo stays identical. Needs
  `GEMINI_API_KEY`. Fallbacks: `gemini_fal_image` (FAL_KEY), `gemini_replicate_image`.
- **Motion shots (like 05):** image-to-video from a Nano Banana still. Read the Layer 3 skill
  first: `.agents/skills/gemini-omni` (Gemini Omni / Veo, same GEMINI_API_KEY),
  `.agents/skills/seedance-2-5`, `.agents/skills/kling-official`. 5 s clips, then slow to 50%
  and cut the best 1.5-3 s.
- **Prompt inspiration:** `.claude/skills/nano-banana-prompts` (15 000+ community prompts,
  `product-marketing.json` has ~46 food ads).
- **Logo overlay + edit:** Remotion / ffmpeg in OpenMontage.

## Prompt templates (English prompts work best; fill the {braces})

Always end image prompts with the **lock line**:
> Packaging and logo must match the reference images exactly: "JONE" above "KEBAB" in heavy
> italic sans, brand red #E3200F and white. No other text, no watermark, no extra logos.
> Photorealistic, shot on a full-frame camera, 50mm, f/2, natural skin texture.

**A. Hands-hold hero (like 01)**
```
Commercial food photo, {4:5}. A {woman in a blush satin halter top / man in a cream knit sweater}
holds a JONE KEBAB {kebab in toasted panini bread, layered doner meat, curly lettuce, tomato,
red and white onion} with both hands at chest height, toward the camera. Face cropped at the lips,
{gold ring}. Warm amber curtain background, soft warm window light from the left, shallow depth of
field, the food tack-sharp. {lock line}
```

**B. Dip / sauce drip action (like 02)**
```
Golden-hour lifestyle food photo, {3:4}. Close-up of a hand dipping {a glazed crispy chicken
wing / a tender} into a small cup of {samurai / white} sauce, a drip of sauce frozen mid-air.
Behind: a white JONE KEBAB box with red logo and red "9" in the corners full of {wings}, a red
JONE KEBAB fry carton, a white branded cup. Orange wooden picnic table, {person in a navy hoodie}
softly out of focus, strong warm backlight and rim light. {lock line}
```

**C. Street carry (like 03)**
```
Sunny lifestyle street photo, {1:1}. A {man in a khaki bomber jacket and jeans} walks on a
European cobblestone pedestrian street with café terraces, smiling, face cropped at the mouth,
carrying a kraft paper JONE KEBAB bag (red logo, red bottom band, red rope handles) at hip height
as the sharp focal point. Morning sun, long soft shadows, people blurred in the background.
{lock line}
```

**D. Product + hands, clean (like 04)**
```
Minimal food photo, {1:1}. A red JONE KEBAB fry carton with white logo full of golden thin fries,
held by one hand while the other hand lifts a few fries. {White hoodie}, dark wood table, plain
warm beige wall, soft daylight. {lock line}
```

**E. Motion shot still + video prompt (like 05)**
Still (9:16): `Macro food photo, a {breaded mozzarella stick / kebab / tender} held by two hands
with nude manicure, dark olive velvet backdrop, warm side key light, steam, shallow depth of field. {lock line}`
Video prompt: `Slow motion macro. The hands slowly pull the {cheese stick} apart, a long glossy
cheese stretch forms, thin wisps of steam rise. Camera static, very slight push-in. No cuts,
no text.` → then slow to 50% and keep the best 1.8-3 s.

## Quality checklist before showing the user

- Logo spelled exactly **JONE / KEBAB** on every pack (AI often writes "JOHN", "JONES", "KEBAP")
  - regenerate if wrong.
- Hands: 5 fingers, natural nails, no fused fingers.
- Food looks hot and fresh (gloss, steam, crumbs), meat texture realistic.
- Only one logo overlay, top-right, white.
- Faces cropped; if a face slipped in, crop or regenerate.
